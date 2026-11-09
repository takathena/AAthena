# ==========================================
# NEXUS IoT - Multi-stage Dockerfile
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
    && useradd -r -u 1000 -s /bin/false -m -d /home/nexus nexus

# Copy Python packages dari builder
COPY --from=builder /root/.local /home/nexus/.local

# Copy aplikasi
COPY --chown=nexus:nexus . /app

# Setup PATH dan PYTHONPATH
ENV PATH=/home/nexus/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=5000 \
    WEB_CONCURRENCY=2

# Buat folder yang dibutuhkan
RUN mkdir -p /app/database /app/logs /app/backup \
    && chown -R nexus:nexus /app

# Entrypoint handle permission & drop privilege
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]

# ✅ Command default: Gunicorn + uvicorn worker (FastAPI v2.0) via run:app
# Jumlah worker dibaca dari WEB_CONCURRENCY (default 2). --max-requests me-recycle worker
# secara berkala; pemilik background tasks yang di-recycle digantikan worker lain (H2).
CMD ["gunicorn", "-k", "uvicorn.workers.UvicornWorker", \
     "--timeout", "60", "--graceful-timeout", "30", "--keep-alive", "5", \
     "--max-requests", "1000", "--max-requests-jitter", "100", \
     "-b", "0.0.0.0:5000", "--access-logfile", "-", "--error-logfile", "-", "run:app"]
