#!/usr/bin/env python3
"""
export_web_config.py — BUILD-TIME bridge from the Python config to the Next.js UI (WEB-01, Phase 4).

Run by the Dockerfile's `web` build stage, before `next build`:

    python export_web_config.py            # write web/lib/generated/products-config.json + check drift
    python export_web_config.py --check    # check only, write nothing (exit 1 on drift)

Why it exists. The Next app (web/) renders the curated catalogue from products_config.py, and
mirrors the ticker groups / colours of config.py in web/lib/config.ts. Both are edited by hand
on the monthly / quarterly maintenance calendar (CLAUDE.md §10). Without this step, a
products_config.py edit would deploy to the Python crawlers but leave the UI showing the old
catalogue — a silent drift, the SC-14 class one level up. So:

  1. products-config.json is REGENERATED from products_config.py on every build (never trusted
     from the upload), with the exact key subset Product/tests/golden_dump.py dumps.
  2. The ticker lists in web/lib/config.ts are CHECKED against config.py; any mismatch exits 1,
     which fails the Railway build — and a failed build leaves the previous deploy running.

Python only reads config here; it imports nothing from web/ and writes nothing but the one JSON.
"""
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import config            # noqa: E402
import products_config   # noqa: E402

OUT = os.path.join(HERE, "web", "lib", "generated", "products-config.json")
CONFIG_TS = os.path.join(HERE, "web", "lib", "config.ts")

# Same subset, same order, as golden_dump.py's out["products_config"].
PC_KEYS = ["GPU_PRODUCTS", "GPU_ENTERPRISE_PRODUCTS", "CPU_PRODUCTS", "CPU_ENTERPRISE_PRODUCTS",
           "RAM_PRODUCTS", "ENTERPRISE_PRODUCT_LAUNCHES", "SRC_PUBLISHED", "SRC_MODELED",
           "DEMAND_INDICATOR_META"]

# Tickers in config.TICKER_MAP that dashboard.py's _CAT_ORDER never grouped either — kept out of
# the sidebar on purpose (parity). Adding a NEW ticker must add it to a group in web/lib/config.ts.
KNOWN_UNGROUPED = {"A50"}


def _plain(o):
    """Same conventions as golden_dump.jsonable() for the plain-Python values products_config holds."""
    if isinstance(o, dict):
        return {str(k): _plain(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_plain(v) for v in o]
    if isinstance(o, float):
        if math.isnan(o):
            return "NaN"
        if math.isinf(o):
            return "Infinity" if o > 0 else "-Infinity"
    return o


def _ts_array(src, name):
    m = re.search(r"export const %s\s*=\s*\[(.*?)\]" % re.escape(name), src, re.S)
    if not m:
        return None
    return re.findall(r'"([^"]*)"', m.group(1))


def check_config_ts():
    with open(CONFIG_TS, encoding="utf-8") as fh:
        src = fh.read()
    errors = []
    for name, py in [("SEMI_COMPANIES", config.SEMI_COMPANIES), ("SEMI_ETFS", config.SEMI_ETFS),
                     ("CHART_COLORS", config.CHART_COLORS)]:
        ts = _ts_array(src, name)
        if ts is None:
            errors.append("web/lib/config.ts: %s not found" % name)
        elif [s.upper() for s in ts] != [s.upper() for s in py]:
            errors.append("%s differs: config.py=%s  config.ts=%s" % (name, list(py), ts))
    grouped = set()
    for name in ["SEMI_COMPANIES", "SEMI_ETFS", "MACRO_OTHER", "TECH_MIXED"]:
        grouped |= set(_ts_array(src, name) or [])
    tickers = set(config.TICKER_MAP)
    missing = sorted(tickers - grouped - KNOWN_UNGROUPED)
    unknown = sorted(grouped - tickers)
    if missing:
        errors.append("tickers in config.TICKER_MAP but in no web/lib/config.ts group: %s" % missing)
    if unknown:
        errors.append("tickers in web/lib/config.ts that config.TICKER_MAP does not define: %s" % unknown)
    return errors


def main():
    check_only = "--check" in sys.argv[1:]
    errors = check_config_ts()
    data = _plain({k: getattr(products_config, k) for k in PC_KEYS})
    text = json.dumps(data, indent=1, ensure_ascii=False, allow_nan=False) + "\n"
    if check_only:
        try:
            with open(OUT, encoding="utf-8") as fh:
                if json.load(fh) != json.loads(text):
                    errors.append("web/lib/generated/products-config.json is stale vs products_config.py")
        except FileNotFoundError:
            errors.append("web/lib/generated/products-config.json missing")
    else:
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        with open(OUT, "w", encoding="utf-8") as fh:
            fh.write(text)
        print("export_web_config: wrote %s (%d keys)" % (os.path.relpath(OUT, HERE), len(data)))
    if errors:
        for e in errors:
            print("export_web_config: DRIFT — " + e, file=sys.stderr)
        sys.exit(1)
    print("export_web_config: web/lib/config.ts matches config.py")


if __name__ == "__main__":
    main()
