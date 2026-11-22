# Dockerfile — THIS IS PROD'S BUILD. Railway builds this service from this file
# (build log: "load build definition from Dockerfile"), whatever railway.toml's
# `builder` line says. Railway's startCommand (`sh startup.sh`) overrides CMD.
#
# Two stages (WEB-01 Phase 4):
#   1. `web`  — builds the Next.js UI in web/ on Node 22.
#   2. final  — crawlers + api_server.py (Flask, no Dash since Phase 5), plus the node
#               binary and web's standalone server. startup.sh runs Next on $PORT and
#               gunicorn api_server:server on 127.0.0.1:8051.
# If stage 1 fails, the whole build fails and Railway keeps the previous deploy. If node
# or the web build is ever absent at runtime, startup.sh exits 1 (healthcheck fails, the
# previous deploy keeps serving). Rollback: archive/dashboard_phase5_20261116/README.md.

# ── Stage 1: build the Next.js UI ───────────────────────────────────────────
FROM node:22-bookworm-slim AS web
# python3 only to run export_web_config.py (stdlib-only: imports config + products_config)
RUN apt-get update && apt-get install -y --no-install-recommends python3 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY config.py products_config.py export_web_config.py ./
COPY web/ web/
# 1. regenerate the UI catalogue from products_config.py; exit 1 on ticker drift
# 2. exact lockfile install. --ignore-scripts is REQUIRED: better-sqlite3's install
#    script is `node-gyp rebuild` (needs g++/make, absent here). Its N-API binaries ship
#    prebuilt in the package (prebuilds/linux-x64.node), and they are what loads — §9 WEB-01f.
# 3. standalone build; static assets are not part of standalone output, copy them in
RUN python3 export_web_config.py \
    && cd web \
    && npm ci --ignore-scripts --no-audit --no-fund \
    && npm run build \
    && cp -r .next/static .next/standalone/.next/static \
    && cp -r public .next/standalone/public

# ── Stage 2: runtime (Python app + node + built UI) ─────────────────────────
FROM python:3.11-slim

WORKDIR /app

# gcc: Python wheels fallback. libstdc++6: needed by the node binary and the
# better-sqlite3 native module copied in below.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Node runtime only (no npm needed at runtime)
COPY --from=web /usr/local/bin/node /usr/local/bin/node

COPY . .
COPY --from=web /app/web/.next/standalone web/.next/standalone

# Cloud providers inject PORT; default 8050 for local docker runs
ENV PORT=8050
ENV HOST=0.0.0.0

# Persistent volume should be mounted at /data — set DB_PATH accordingly
ENV DB_PATH=/data/semiconductor_data.db

EXPOSE $PORT

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${PORT}/health')"

# Same entrypoint as Railway's startCommand, so a manual `docker run` behaves like prod
CMD ["sh", "startup.sh"]
