#!/bin/bash
# ==========================================
# AAguard IoT - Docker Entrypoint
# Handle permission & drop privilege dari root ke aaguard
# ==========================================

set -e

log() {
    echo "[entrypoint] $*"
}

mkdir -p /app/database /app/logs /app/backup

if [ "$(id -u)" = "0" ]; then
    log "Running as root, fixing permissions..."

    chown -R aaguard:aaguard /app/database /app/logs /app/backup 2>/dev/null || true
    chown -R aaguard:aaguard /app 2>/dev/null || true

    if ! gosu aaguard touch /app/logs/.write_test 2>/dev/null; then
        log "WARNING: aaguard user cannot write to /app/logs"
    else
        rm -f /app/logs/.write_test
        log "Permissions OK"
    fi

    log "Dropping privileges to aaguard user..."
    exec gosu aaguard "$@"
else
    log "Running as $(id -un) (uid=$(id -u))"
    exec "$@"
fi