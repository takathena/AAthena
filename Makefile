# ==========================================
# NEXUS IoT - Makefile
# ==========================================

COMPOSE_PROD := docker compose -f docker-compose.yml

.PHONY: help dev install install-dev run run-prod backup test lint health clean \
        docker-build docker-up docker-dev-up docker-down docker-logs docker-restart docker-shell \
        docker-rebuild

GREEN  := \033[0;32m
YELLOW := \033[1;33m
RED    := \033[0;31m
NC     := \033[0m

VENV        := venv
PYTHON      := $(VENV)/bin/python
PIP         := $(VENV)/bin/pip
PORT        := $(shell grep '^PORT' .env 2>/dev/null | cut -d= -f2 | tr -d ' ' || echo 5000)
NGINX_PORT  := $(shell grep '^NGINX_PORT' .env 2>/dev/null | cut -d= -f2 | tr -d ' ' || echo 4455)

help:
	@echo "$(GREEN)NEXUS IoT - Available Commands$(NC)"
	@echo ""
	@echo "  $(YELLOW)Development:$(NC)"
	@echo "    make dev            Setup virtualenv & install dependencies"
	@echo "    make install        Install dependencies produksi saja"
	@echo "    make install-dev    Install dependencies produksi + dev (pytest, ruff)"
	@echo "    make run            Jalankan dev server (python run.py)"
	@echo "    make run-prod       Jalankan production server (Gunicorn)"
	@echo "    make backup         Backup database manual"
	@echo "    make test           Jalankan pytest"
	@echo "    make lint           Lint dengan ruff (undefined name, import tak terpakai)"
	@echo "    make health         Test health endpoint"
	@echo "    make clean          Hapus venv, cache, log, backup lama"
	@echo ""
	@echo "  $(YELLOW)Docker:$(NC)"
	@echo "    make docker-build   Build image"
	@echo "    make docker-up      Start container produksi (tanpa override dev)"
	@echo "    make docker-dev-up  Start container development (mount kode)"
	@echo "    make docker-down    Stop container"
	@echo "    make docker-restart Restart container"
	@echo "    make docker-rebuild Rebuild dari nol + restart"
	@echo "    make docker-logs    Lihat log realtime"
	@echo "    make docker-shell   Masuk ke shell container"
	@echo ""

# ==========================================
# Development
# ==========================================
dev: $(VENV)/bin/activate
	@echo "$(GREEN)Virtualenv ready!$(NC)"
	@echo "$(YELLOW)Jalankan: make run$(NC)"

$(VENV)/bin/activate:
	@echo "$(GREEN)Creating virtualenv...$(NC)"
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements-dev.txt
	@if [ ! -f .env ]; then \
		echo "$(YELLOW)Creating .env from .env.example...$(NC)"; \
		cp .env.example .env; \
		echo "$(RED)PENTING: Edit .env, set SECRET_KEY dan IOT_PASSWORD!$(NC)"; \
	fi
	@mkdir -p database logs backup
	@echo "$(GREEN)Setup complete!$(NC)"

install:
	$(PIP) install -r requirements.txt

install-dev:
	$(PIP) install -r requirements-dev.txt

run:
	@if [ ! -f .env ]; then echo "$(RED).env tidak ada! Jalankan: make dev$(NC)"; exit 1; fi
	@echo "$(GREEN)Starting dev server on port $(PORT)...$(NC)"
	$(PYTHON) run.py

run-prod:
	@if [ ! -f .env ]; then echo "$(RED).env tidak ada!$(NC)"; exit 1; fi
	@echo "$(GREEN)Starting production server (Gunicorn)...$(NC)"
	$(VENV)/bin/gunicorn -w 2 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:$(PORT) \
		--timeout 60 --graceful-timeout 30 --keep-alive 5 \
		--max-requests 1000 --max-requests-jitter 100 \
		--access-logfile - --error-logfile - run:app

backup:
	@mkdir -p backup
	# Nama iot_manual-*.db (bukan manual-*.db) agar ikut retensi/pembersihan
	# app (BACKUP_RETENTION_DAYS/BACKUP_MIN_KEEP, pola iot_*.db) + UI backup.
	$(PYTHON) -c "import sqlite3; from datetime import datetime; \
		src=sqlite3.connect('database/iot.db'); \
		dst=sqlite3.connect(f'backup/iot_manual-{datetime.now():%Y%m%d_%H%M%S}.db'); \
		src.backup(dst); dst.close(); src.close(); \
		print('Backup done')"

test:
	@echo "$(GREEN)Menjalankan pytest...$(NC)"
	$(PYTHON) -m pytest -q

lint:
	@echo "$(GREEN)Lint (ruff)...$(NC)"
	$(PYTHON) -m ruff check app run.py

health:
	@echo "$(GREEN)Testing health endpoint...$(NC)"
	@curl -s http://localhost:$(PORT)/health | python3 -m json.tool || echo "$(RED)Server tidak jalan$(NC)"

clean:
	@echo "$(YELLOW)Cleaning...$(NC)"
	rm -rf $(VENV)
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .pytest_cache
	@echo "$(GREEN)Clean!$(NC)"

# ==========================================
# Docker
# ==========================================
docker-build:
	$(COMPOSE_PROD) build

docker-up:
	@mkdir -p database logs backup
	@chown -R 1000:1000 database logs backup 2>/dev/null || true
	$(COMPOSE_PROD) up -d --build
	@echo "$(GREEN)Waiting for health check...$(NC)"
	@sleep 15
	@$(COMPOSE_PROD) ps
	@echo ""
	@echo "$(GREEN)Akses: http://localhost:$(NGINX_PORT)$(NC)"

# Development: docker-compose.override.yml dimuat otomatis (mount app/templates/static)
docker-dev-up:
	@mkdir -p database logs backup
	@chown -R 1000:1000 database logs backup 2>/dev/null || true
	docker compose up -d --build
	@echo "$(YELLOW)Mode DEVELOPMENT (kode di-mount). Untuk produksi: make docker-up$(NC)"

docker-down:
	docker compose down

docker-restart:
	docker compose restart

docker-rebuild:
	$(COMPOSE_PROD) down
	$(COMPOSE_PROD) build --no-cache
	@mkdir -p database logs backup
	@chown -R 1000:1000 database logs backup 2>/dev/null || true
	$(COMPOSE_PROD) up -d
	@echo "$(GREEN)Waiting for health check...$(NC)"
	@sleep 20
	@$(COMPOSE_PROD) ps

docker-logs:
	docker compose logs -f

docker-shell:
	docker compose exec nexus-iot bash