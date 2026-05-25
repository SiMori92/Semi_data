"""
ibkr_relay.py — IBKR → Cloud Relay
====================================
Run this script on your LOCAL machine (where TWS / IB Gateway is running).
It connects to Interactive Brokers, fetches implied-volatility data for all
configured tickers, then POSTs the results to your cloud-hosted dashboard.

Setup:
  1. Make sure TWS or IB Gateway is running on your local machine.
  2. Set RELAY_API_KEY and CLOUD_URL in ibkr_relay_config.json  (see below)
     OR set environment variables RELAY_API_KEY and CLOUD_URL.
  3. Run:  python ibkr_relay.py

The cloud dashboard exposes  POST /api/upload-iv  which accepts the payload
and writes it to the SQLite database on the persistent volume.

ibkr_relay_config.json example:
{
  "cloud_url":     "https://your-app.railway.app",
  "relay_api_key": "your-secret-key-here",
  "tickers":       []   // empty = all tickers from ibkr_config.json
}
"""

import json
import os
import sys
import time
import argparse
from datetime import datetime
from config import now_hkt as _now_hkt

import requests  # stdlib-requests, not ib_insync — for the HTTP POST

# Re-use the existing IBKR crawler logic
from ibkr_options_crawler import (
    load_config,
    ibkr_is_enabled,
    connect,
    disconnect,
    build_contract,
    fetch_iv_history,
    calculate_iv_metrics,
)

# ── Config ────────────────────────────────────────────────────────────────────

RELAY_CONFIG_FILE = "ibkr_relay_config.json"

DEFAULT_RELAY_CONFIG = {
    "cloud_url":     "",
    "relay_api_key": "",
    "tickers":       [],
}


def load_relay_config() -> dict:
    """Load relay config from JSON file, falling back to env vars."""
    cfg = dict(DEFAULT_RELAY_CONFIG)

    if os.path.exists(RELAY_CONFIG_FILE):
        with open(RELAY_CONFIG_FILE) as f:
            cfg.update(json.load(f))

    # Environment variables override the file
    if os.environ.get("CLOUD_URL"):
        cfg["cloud_url"] = os.environ["CLOUD_URL"]
    if os.environ.get("RELAY_API_KEY"):
        cfg["relay_api_key"] = os.environ["RELAY_API_KEY"]

    return cfg


def save_default_relay_config():
    """Write a blank ibkr_relay_config.json so the user can fill it in."""
    if not os.path.exists(RELAY_CONFIG_FILE):
        with open(RELAY_CONFIG_FILE, "w") as f:
            json.dump({
                "_doc": {
                    "cloud_url": "Full URL of your hosted dashboard, e.g. https://your-app.railway.app",
                    "relay_api_key": "Must match the RELAY_API_KEY env var set on the cloud app",
                    "tickers": "List of display-name tickers to relay, e.g. ['NVDA','AMD']. Empty = all.",
                },
                "cloud_url": "",
                "relay_api_key": "",
                "tickers": [],
            }, f, indent=2)
        print(f"Created {RELAY_CONFIG_FILE} — please fill in cloud_url and relay_api_key.")


# ── Main relay logic ──────────────────────────────────────────────────────────

def run_relay(tickers_override=None):
    relay_cfg = load_relay_config()

    cloud_url = relay_cfg.get("cloud_url", "").rstrip("/")
    api_key   = relay_cfg.get("relay_api_key", "")

    if not cloud_url:
        print("❌  cloud_url is not set in ibkr_relay_config.json or CLOUD_URL env var.")
        print("    Example: https://your-app.railway.app")
        sys.exit(1)

    # Load IBKR settings
    ibkr_cfg = load_config()

    if not ibkr_is_enabled():
        print("❌  IBKR is disabled in ibkr_config.json  (set 'enabled': true).")
        sys.exit(1)

    # Determine tickers to relay
    if tickers_override:
        tickers = tickers_override
    elif relay_cfg.get("tickers"):
        tickers = relay_cfg["tickers"]
    else:
        # All tickers from ibkr_config.json
        tickers = [
            t for t in ibkr_cfg.get("ticker_contracts", {}).keys()
            if not t.startswith("_")
        ]

    skip = set(ibkr_cfg.get("skip_tickers", {}).get("list", []))
    tickers = [t for t in tickers if t not in skip]

    print(f"📡  Relaying IV data for {len(tickers)} tickers → {cloud_url}")
    print(f"    Tickers: {', '.join(tickers)}\n")

    # Connect to IBKR
    print("🔌  Connecting to IBKR TWS / IB Gateway …")
    ib = connect(ibkr_cfg["connection"])
    if ib is None:
        print("❌  Could not connect to IBKR. Is TWS / IB Gateway running?")
        sys.exit(1)
    print("✅  Connected.\n")

    windows = ibkr_cfg.get("crawl_settings", {}).get("iv_windows", {
        "1_month": 21, "1_quarter": 63, "6_months": 126, "1_year": 252
    })
    delay = ibkr_cfg.get("crawl_settings", {}).get("delay_between_requests_s", 1.5)

    snapshots = []
    errors    = []

    for ticker in tickers:
        try:
            contract = build_contract(ticker, ibkr_cfg)
            df = fetch_iv_history(ib, contract, ticker, ibkr_cfg)

            if df is None or df.empty:
                print(f"  ⚠️  {ticker}: no IV data returned, skipping.")
                continue

            metrics = calculate_iv_metrics(df, windows)
            as_of   = _now_hkt().strftime("%Y-%m-%dT%H:%M:%S")

            snapshots.append({
                "ticker":       ticker,
                "iv_current":   metrics.get("iv_current"),
                "iv_1m_avg":    metrics.get("iv_1m_avg"),
                "iv_1q_avg":    metrics.get("iv_1q_avg"),
                "iv_6m_avg":    metrics.get("iv_6m_avg"),
                "iv_1y_avg":    metrics.get("iv_1y_avg"),
                "iv_pct_vs_1y": metrics.get("iv_pct_vs_1y"),
                "iv_52w_high":  metrics.get("iv_52w_high"),
                "iv_52w_low":   metrics.get("iv_52w_low"),
                "as_of":        as_of,
            })
            print(f"  ✅  {ticker}: IV={metrics.get('iv_current', 0):.1%}  "
                  f"(1Y pct={metrics.get('iv_pct_vs_1y', 0):.0f}%)")

        except Exception as e:
            print(f"  ❌  {ticker}: {e}")
            errors.append((ticker, str(e)))

        time.sleep(delay)

    disconnect(ib)
    print()

    if not snapshots:
        print("⚠️  No snapshots collected — nothing to send.")
        sys.exit(0)

    # POST to cloud
    endpoint = f"{cloud_url}/api/upload-iv"
    headers  = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key

    print(f"📤  POSTing {len(snapshots)} snapshots → {endpoint} …")
    try:
        resp = requests.post(
            endpoint,
            headers=headers,
            data=json.dumps({"snapshots": snapshots}),
            timeout=30,
        )
        if resp.status_code == 200:
            result = resp.json()
            print(f"✅  Cloud accepted {result.get('stored', '?')} snapshots.")
        elif resp.status_code == 401:
            print("❌  401 Unauthorized — check RELAY_API_KEY matches on both ends.")
        else:
            print(f"❌  Server returned {resp.status_code}: {resp.text[:200]}")
    except requests.RequestException as e:
        print(f"❌  HTTP error: {e}")

    if errors:
        print(f"\n⚠️  {len(errors)} ticker(s) had errors:")
        for ticker, msg in errors:
            print(f"    {ticker}: {msg}")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Relay IBKR implied-volatility data to the cloud dashboard."
    )
    parser.add_argument(
        "--tickers", nargs="+", metavar="TICKER",
        help="Override tickers to relay (default: all from ibkr_config.json)"
    )
    parser.add_argument(
        "--init-config", action="store_true",
        help="Create a blank ibkr_relay_config.json and exit"
    )
    args = parser.parse_args()

    if args.init_config:
        save_default_relay_config()
        sys.exit(0)

    run_relay(tickers_override=args.tickers)
