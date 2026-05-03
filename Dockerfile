FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
# ib_insync is only needed locally (IBKR relay runs on your machine, not cloud)
# Install without it to keep the image lean; it's safe to keep if you prefer.
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Cloud providers inject PORT; default 8050 for local docker runs
ENV PORT=8050
ENV HOST=0.0.0.0

# Persistent volume should be mounted at /data — set DB_PATH accordingly
ENV DB_PATH=/data/semiconductor_data.db

EXPOSE $PORT

# Health check (uses the /health endpoint added to dashboard.py)
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${PORT}/health')"

CMD ["sh", "-c", "gunicorn dashboard:server --bind 0.0.0.0:$PORT --workers 2 --timeout 120"]
