# ==========================================
# AAguard IoT - Multi-stage Dockerfile
# ==========================================
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt


FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gosu \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -r -u 1000 -s /bin/false -m -d /home/aaguard aaguard

# Copy Python packages dari builder
COPY --from=builder /root/.local /home/aaguard/.local

# Copy aplikasi
COPY --chown=aaguard:aaguard . /app

# Setup PATH dan PYTHONPATH
ENV PATH=/home/aaguard/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=5000 \
    WEB_CONCURRENCY=2

# Buat folder yang dibutuhkan
RUN mkdir -p /app/database /app/logs /app/backup \
    && chown -R aaguard:aaguard /app

# Entrypoint handle permission & drop privilege
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE ${PORT:-5000}

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:${PORT:-5000}/health || exit 1

USER aaguard

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]

# ✅ Command default: Gunicorn + uvicorn worker (FastAPI v2.0) via run:app
# Worker & port dibaca dari env (WEB_CONCURRENCY, PORT). Shell-form agar
# ${...} di-expand oleh /bin/sh saat container start.
# --max-requests me-recycle worker secara berkala; pemilik background tasks
# yang di-recycle digantikan worker lain (H2).
CMD gunicorn -k uvicorn.workers.UvicornWorker -w ${WEB_CONCURRENCY:-2} \
    --timeout 60 --graceful-timeout 30 --keep-alive 5 \
    --max-requests 1000 --max-requests-jitter 100 \
    -b 0.0.0.0:${PORT:-5000} --access-logfile - --error-logfile - run:app
