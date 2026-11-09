# Big Refactor + Docker Deploy Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor besar NEXUS IoT tanpa mengubah fitur/kegunaan (API, web, alert, RFID, multi-user, background, backup/restore, chat), lalu deploy via Docker Compose dan verifikasi situs berjalan semestinya.

**Architecture:** Pecah monolit `api.py` (2984 baris, 59 route) dan `dashboards.py` (955 baris) menjadi package per-domain dengan layer services tipis, pertahankan kontrak HTTP/JSON + schema persis, lalu validasi lewat pytest + smoke Docker (health → login → dashboard → ingest → CRUD → background).

**Tech Stack:** Python 3.11, Flask 3.1.3, SQLite WAL (schema v18), Gunicorn gthread, Nginx alpine, Docker Compose v2, `pytest`, `ruff` (E9,F).

**Spec:** Request saat ini: "lanjutkan refactor besar-besaran, boleh ubah sistem, jangan ubah fitur/kegunaan; boleh tambah fitur bila logika kurang matang; deploy dengan docker dan cek website berjalan semestinya; install skill/dependency yang diperlukan." Refactor foundation sebelumnya (config helper, factory split, `database.py`→`migrations.py`, `api.py`→`api_common.py`) adalah fondasi plan ini.

## Global Constraints

- Python 3.11; Flask 3.1.3; SQLite WAL; schema tetap v18 (`app/database.SCHEMA_VERSION==18`); `run.py` (`run:app`) dan Gunicorn `run:app` tetap entry point.
- Kontrak tidak berubah: semua path `/api/v1/*`, status code, bentuk JSON `{success, error?, ...}`, auth session + CSRF, rate limit, API key SHA-256, CSP/HSTS, dan semua nama env di `.env.example` (PORT 5000 internal, NGINX_PORT 5008 publik).
- DB_PATH default `database/iot.db`, WAL, `busy_timeout=30000`; migrasi hanya append (jangan edit v1..v18), tambah v19 bila perlu.
- Docker: `docker-compose.yml` (nexus-iot + nginx), Dockerfile multi-stage non-root UID 1000, volume `database/`, `logs/`, `backup/`, `.env` ro.
- `ruff check app run.py` harus hijau; `pytest -q` hijau sebelum deploy Docker.

## Review Focus

- **Payload device jelek / berlebih:** JSON rusak, `data` bukan dict datar, NaN/Infinity, string >64, >32 key, RFID UID tak valid (`0x...`), > `DATA_MAX_BYTES` (8192) — harus 400/413 tanpa menyimpan yatim.
- **Auth & akses lintas user:** tanpa session/CSRF, non-admin ubah/hapus device/kartu, user A baca dashboard user B, logout GET vs POST, throttle login per username+IP & per-IP — harus 401/403/404 dan tidak bocor error/secret.
- **Alert state machine & ack:** healthy→warning→danger→warning→healthy + hysteresis per-sensor, ack meng-skip retrigger bila severity sama/ringan tapi retrigger bila memburuk, offline timeout = 2× interval (10–86400 dtk, median 5 sampel) — harus tidak flip-flop / tidak spam notifikasi.
- **Efek samping DB & background:** `database is locked`, multi-worker Gunicorn + file lock `db-init`/`nexus-background`, cleanup 24 jam + VACUUM >1000 baris, backup `iot_*.db` (min keep 3, jangan hapus `pre-restore-*`), restore tertunda diterapkan saat start —
- **Edge deploy/browser:** `/health` 503 tanpa bocor path, 500 tanpa bocor `str(e)`, CSP/HSTS header, static cache-busting `?v=<mtime>`, API key plain hanya sekali, CSV export anti formula-injection (`=+-@`), purge tanpa batas tanggal ditolak.

---

## File Structure

```
docs/superpowers/plans/2026-11-09-big-refactor-docker-verify.md  # plan ini
app/
  __init__.py              # factory (sudah split: _apply_proxy_fix, _init_extensions, ...)
  config.py                # helper _env_* (sudah); target: tetap, reload-safe
  database.py              # koneksi + init runner (132 baris, jangan membesar lagi)
  migrations.py            # v1..v18 verbatim (923 baris); v19+ append
  api_common.py            # helper bersama hasil refactor awal (243 baris)
  services/                # BARU: logika murni, tanpa Flask
    __init__.py
    devices.py             # _detect_interval, status transition, bulk import parse
    purge.py               # _parse_purge_request, _purge_where, _purge_preview (pindah dari api_common)
    attendance.py          # dedup 30 dtk, report check-in/out
    alerts_core.py         # severity band + hysteresis (re-export dari alerts.py)
  api/                     # BARU: package pecahan api.py (59 route total, prefix /api/v1 dipertahankan)
    __init__.py            # api_bp + import semua modul; re-export api_common untuk kompatibilitas
    ingest.py              # POST /data
    devices.py             # GET/POST/PUT/DELETE /devices, history, export, alert-rules, regenerate, bulk-import
    alerts.py              # /alerts*, /alerts/trend
    attendance.py          # /cardholders*, /attendance*
    dashboards_api.py      # /dashboard, /metrics/*
    users.py               # /users*, /users/me*, /permissions*
    system.py              # /system/*, /notifications/*, global alert-rules, purge/preview/delete, vacuum, audit-log
  dashboards/              # BARU: pecahan dashboards.py (23 route, prefix /api/v1)
    __init__.py            # dashboards_bp + re-export _find_dashboard_by_slug (dipakai views.py)
    core.py                # slug/member/default, _LIST_SQL, _check_*
    analytics.py           # tabs + widgets
    telegram.py            # telegram config/test
  alerts.py                # tetap; services.alerts_core hanya re-export thin
  chat.py / background.py / notifier.py  # tetap publik; tambah thin wrapper bila perlu
  __init__                 # register api.api_bp, dashboards.dashboards_bp, dst — tanpa ubah urutan
tests/                     # tambah test_refactor_* tanpa ubah test lama
docker-compose.yml / Dockerfile / nginx/*  # target hardening Task 7
.env                       # hasil generate (bukan commit); .env.example tetap sumber kebenaran
```

Aturan split: satu file = satu domain, route handler tipis → services; kompatibilitas import lama wajib lolos (`from app.database import SCHEMA_VERSION, _migrate_v*`; `from app.api import api_bp, get_db_context, sqlite3, _clean_timestamp, PURGE_TABLES`).

## Task 1: Baseline + Docker prasyarat

**Files:**
- Modify: `.gitignore` (pastikan `database/`, `logs/`, `backup/` hasil lokal tidak ikut commit bila belum)
- Test: `tests/test_refactor_baseline.py` (BARU, tipis)

**Interfaces:**
- Consumes: `app.__version__`, `/health`, `/ready`
- Produces: baseline hijau untuk refactor dan deploy (dipakai Task 8)

- [ ] **Step 1: Write the failing (sanity) test**

```python
def test_health_and_ready(anon_client):
    assert anon_client.get('/health').status_code == 200
    assert anon_client.get('/ready').status_code == 200
    assert anon_client.get('/health').get_json()['version'] == __import__('app').__version__
```

- [ ] **Step 2: Run test to verify it passes (baseline)**

Run: `python3 -m pytest tests/test_refactor_baseline.py -v`
Expected: PASS

- [ ] **Step 3: Pastikan Docker siap (install bila absen)**

```bash
docker --version || apt-get update && apt-get install -y docker.io docker-compose-plugin
docker compose version
mkdir -p database logs backup
cp -n .env.example .env
python3 -c "import secrets; print(secrets.token_hex(32))"
# isi SECRET_KEY (>=32 char, bukan CHANGE_ME_*) dan IOT_PASSWORD (>=8, bukan admin/password/change-me) di .env
```

- [ ] **Step 4: Run full baseline**

Run: `python3 -m pytest -q && python3 -m ruff check app run.py`
Expected: 0 fail.

- [ ] **Step 5: Commit**

```bash
git add tests/test_refactor_baseline.py .gitignore
git commit -m "test: baseline refactor + docker prasyarat"
```

## Task 2: Services layer (pindah logika murni, tanpa Flask)

**Files:**
- Create: `app/services/__init__.py`, `app/services/devices.py`, `app/services/purge.py`, `app/services/attendance.py`
- Modify: `app/api_common.py` (thin re-export), `app/api.py` (import dari services)
- Test: `tests/test_refactor_services.py`

**Interfaces:**
- Consumes: `app.utils.parse_datetime`, `app.database.get_db_context` (hanya di boundary), `PURGE_TABLES`
- Produces: `services.devices.detect_interval(conn, device_id) -> int | None`; `services.purge.parse_purge_request(payload) -> (spec|None, err|None)`, `purge_where`, `purge_preview(conn, spec)`; `services.attendance.dedup_cutoff()` + `build_report(rows)`

- [ ] **Step 1: Failing test**

```python
def test_detect_interval_needs_samples(db_path, make_device):
    import sqlite3
    from app.services.devices import detect_interval
    assert detect_interval(object(), 'x') is None  # belum cukup sampel → None, tanpa tulis DB

def test_purge_needs_date():
    from app.services.purge import parse_purge_request
    spec, err = parse_purge_request({'tables': ['sensor_data']})
    assert spec is None and 'minimal salah satu' in err
```

- [ ] **Step 2: Run → FAIL (module not found)**

Run: `python3 -m pytest tests/test_refactor_services.py -v`
Expected: FAIL `ModuleNotFoundError: app.services`

- [ ] **Step 3: Implement services (copy verbatim dari api_common, tanpa ubah isi)**

`services/devices.py`: `_detect_interval`→`detect_interval` + konstanta `AUTO_INTERVAL_*`; `services/purge.py`: `PURGE_TABLES`, `PURGE_BATCH`, `_parse_purge_request`→`parse_purge_request`, `_purge_where`→`purge_where`, `_purge_preview`→`purge_preview`; `services/attendance.py`: dedup/report helper dipakai `api.attendance`. `api_common.py` re-export alias lama (`_detect_interval = detect_interval`, dst).

- [ ] **Step 4: Run → PASS + regresi**

Run: `python3 -m pytest tests/test_refactor_services.py tests/test_phase2_interval.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services app/api_common.py app/api.py tests/test_refactor_services.py
git commit -m "refactor: services layer (devices/purge/attendance)"
```

## Task 3: Pecah `api.py` → `app/api/` package (59 route)

**Files:**
- Create: `app/api/{__init__,ingest,devices,alerts,attendance,dashboards_api,users,system}.py` (pindah baris per-route verbatim, ganti sumber helper jadi `app.services`/`api_common`)
- Modify: `app/__init__.py` (`from app.api import api_bp` tetap, tapi sekarang package)
- Test: `tests/test_refactor_api_package.py`

**Interfaces:**
- Consumes: `services.*`, `api_common.*`, `app.database.get_db_context`, `app.extensions.limiter, csrf`, `app.auth.login_required, admin_required`
- Produces: `app.api.api_bp` (prefix `/api/v1`, 59 route terdaftar), kompatibilitas `app.api.get_db_context`, `app.api.sqlite3`, `app.api._clean_timestamp`, `app.api.PURGE_TABLES`

- [ ] **Step 1: Failing test (route registry)**

```python
def test_api_route_count(app):
    rules = [r.rule for r in app.url_map.iter_rules() if r.rule.startswith('/api/v1/')]
    assert '/api/v1/data' in rules
    assert len([r for r in rules if r.startswith('/api/v1/devices')]) >= 10
    assert len([r for r in rules if r.startswith('/api/v1/alerts')]) >= 7
```

- [ ] **Step 2: Run → FAIL/skip bila package belum ada (atau lolos baseline, catat jumlah)**

Run: `python3 -m pytest tests/test_refactor_api_package.py -v`
Expected: catat total `/api/v1/` aktif (59 di `api.py` monolit).

- [ ] **Step 3: Pindah route verbatim per file (jangan ubah logika)**

Urutan aman: `ingest.py` (POST /data) → `devices.py` → `alerts.py` → `attendance.py` → `dashboards_api.py` → `users.py` → `system.py`. `__init__.py` definisi `api_bp = Blueprint('api', ..., url_prefix='/api/v1')`, import semua modul (urutan import = urutan registrasi lama), re-export helper + `get_db_context, sqlite3` dari package root. Hapus `app/api.py`.

- [ ] **Step 4: Run → PASS + full suite**

Run: `python3 -m pytest -q && python3 -m ruff check app run.py`
Expected: PASS, `grep -c "@api_bp.route" app/api/*.py` total 59.

- [ ] **Step 5: Commit**

```bash
git add app/api app/api.py app/__init__.py tests/test_refactor_api_package.py
git commit -m "refactor: pecah api.py jadi package per-domain (59 route)"
```

## Task 4: Pecah `dashboards.py` → `app/dashboards/` package (23 route)

**Files:**
- Create: `app/dashboards/{__init__,core,analytics,telegram}.py`
- Modify: `app/__init__.py`, `app/views.py` (`from app.dashboards import _find_dashboard_by_slug` tetap jalan via re-export)
- Test: `tests/test_refactor_dashboards_pkg.py`

**Interfaces:**
- Consumes: `app.workspace`, `app.auth.ensure_user_dashboard`, `app.database.get_db_context`
- Produces: `app.dashboards.dashboards_bp`, `app.dashboards._find_dashboard_by_slug(conn, slug, user_id)` (re-export)

- [ ] **Step 1: Failing test**

```python
def test_dashboards_package_imports():
    from app.dashboards import dashboards_bp, _find_dashboard_by_slug  # noqa
    assert dashboards_bp is not None
```

- [ ] **Step 2: Run → FAIL ModuleNotFoundError**

Run: `python3 -m pytest tests/test_refactor_dashboards_pkg.py -v`
Expected: FAIL

- [ ] **Step 3: Pindah verbatim** `_get_user_id`, `_check_*`, `_find_dashboard_by_slug`, `_LIST_SQL`, route core/analytics/telegram ke file masing-masing; `__init__.py` re-export.

- [ ] **Step 4: Run → PASS (`pytest -q`, `ruff check`)**

- [ ] **Step 5: Commit**

```bash
git add app/dashboards app/dashboards.py tests/test_refactor_dashboards_pkg.py
git commit -m "refactor: pecah dashboards.py jadi package"
```

## Task 5: Rapikan alerts/chat/background/notifier (thin, tanpa ubah struktur)

**Files:**
- Modify: `app/alerts.py` (pindah band+hysteresis ke `services/alerts_core.py` sebagai re-export), `app/chat.py`, `app/background.py`, `app/notifier.py` (hanya hapus duplikasi import, tambah komentar `shortcut:` bila ada)
- Test: `tests/test_phase1_alert_rules.py`, `tests/test_phase4_chat.py`, `tests/test_phase3_background.py` (ada, tidak diubah)

**Interfaces:**
- Consumes: `Config.ALERT_RULES`, `validate_single_alert_rule`
- Produces: `services.alerts_core.evaluate_severity(value, rule)`, `apply_hysteresis(...)` (alias dari `alerts._evaluate_severity`, `alerts._apply_hysteresis`)

- [ ] **Step 1: Jalankan test lama sebagai baseline**

Run: `python3 -m pytest tests/test_phase1_alert_rules.py tests/test_phase4_chat.py tests/test_phase3_background.py -q`
Expected: PASS

- [ ] **Step 2: Buktikan alert band pin dengan test rantai**

```python
def test_alert_band_nested():
    from app.services.alerts_core import evaluate_severity
    RULE = {'healthy': {'min': 6, 'max': 28}, 'warning': {'min': 0, 'max': 32}, 'danger': {'min': -10, 'max': 40}}
    assert evaluate_severity(25, RULE) == 'healthy'
```

- [ ] **Step 3: Pindah implementasi ke services, `alerts.py` re-export (logika tidak berubah)**

- [ ] **Step 4: Run → PASS**

Run: `python3 -m pytest tests/test_phase1_alert_rules.py tests/test_phase4_chat.py tests/test_phase3_background.py tests/test_phase3_notifier.py -q`

- [ ] **Step 5: Commit**

```bash
git add app/services/alerts_core.py app/alerts.py app/chat.py app/background.py app/notifier.py
git commit -m "refactor: alerts core ke services (re-export)"
```

## Task 6: Frontend/template sanity (jangan ubah fitur)

**Files:**
- Modify: hanya bila ada error CSP/static — `templates/*.html`, `static/js/*.js`, `static/css/*.css`
- Test: `tests/test_phase3_infra.py`, `tests/test_paket_a_ui.py`, `tests/test_redesain_fase3.py`

**Interfaces:**
- Consumes: `app/__init__.py` `_register_static_cache_bust`, `_register_security_headers`
- Produces: halaman `/login`, `/`, `/mobile`, `/device/<id>` render 200, tidak ada referensi path static mati

- [ ] **Step 1: Baseline render**

```python
def test_login_renders(anon_client):
    assert anon_client.get('/login').status_code == 200
```

- [ ] **Step 2: Run → PASS (atau catat yang sudah merah)**

Run: `python3 -m pytest tests/test_phase3_infra.py tests/test_paket_a_ui.py tests/test_redesain_fase3.py -q`

- [ ] **Step 3: Perbaiki hanya yang pecah oleh refactor backend** (contoh: `url_for('static')` tanpa file, CSP `connect-src` memblokir Leaflet tile) — jangan ubah tata letak/fitur.

- [ ] **Step 4: Run → PASS**

- [ ] **Step 5: Commit** (`git commit -m "fix(web): sanity pasca-refactor"` bila ada perubahan; bila tidak, tetap catat di ringkasan plan)

## Task 7: Hardening Docker (tanpa ubah stack)

**Files:**
- Modify: `Dockerfile`, `docker-compose.yml`, `docker-compose.override.yml`, `docker-entrypoint.sh`, `nginx/nginx.conf`, `nginx/conf.d/nexus.conf`, `.dockerignore`
- Test: `tests/test_phase3_infra.py`, `tests/test_phase3_backup.py`, `tests/test_phase3_restore.py`

**Interfaces:**
- Consumes: `PORT`, `NGINX_PORT`, `WEB_CONCURRENCY`, `NEXUS_LOCK_DIR`, `BACKUP_DIR`, `LOG_FILE`
- Produces: `make docker-up` → nginx :5008 → Flask :5000 → `/health` 200, `/login` 200

- [ ] **Step 1: Failing/checklist test**

```python
def test_dockerfile_nonroot():
    assert 'useradd' in open('Dockerfile').read() or 'USER nexus' in open('Dockerfile').read()
```

- [ ] **Step 2: Run → PASS baseline**

Run: `python3 -m pytest tests/test_phase3_infra.py tests/test_phase3_backup.py tests/test_phase3_restore.py -q`

- [ ] **Step 3: Hardening minimal (jangan ganti stack)**

Bila belum ada: healthcheck `CMD curl -f http://localhost:${PORT}/health`, `proxy_read_timeout 180s` untuk `/api/v1/chat`, volume `./database:./logs:./backup` + `chown 1000:1000`, `.dockerignore` untuk `venv/.venv/tests/.github`, build multi-stage cache-friendly (requirements layer dulu). Jangan expose Flask ke host (hanya Nginx 5008).

- [ ] **Step 4: Build check**

Run: `docker compose -f docker-compose.yml config; docker compose -f docker-compose.yml build`
Expected: build sukses, `docker compose ps` (healthy bila sudah up).

- [ ] **Step 5: Commit**

```bash
git add Dockerfile docker-compose.yml docker-compose.override.yml nginx/ .dockerignore
git commit -m "chore(docker): hardening compose/nginx/healthcheck"
```

## Task 8: Deploy Docker + verifikasi website end-to-end

**Files:**
- Test: `tests/test_refactor_deploy.py` (smoke HTTP lokal, bukan ci) + checklist manual di bawah

**Interfaces:**
- Consumes: `.env` (SECRET_KEY, IOT_PASSWORD), `NGINX_PORT` (default 5008), `PORT` (5000)
- Produces: situs live: `GET /health → 200`, `GET /login → 200`, login → `GET / → 200`, ingest device → data muncul

- [ ] **Step 1: Siapkan `.env` & start**

```bash
mkdir -p database logs backup && chown -R 1000:1000 database logs backup || true
docker compose -f docker-compose.yml up -d --build
sleep 15; docker compose -f docker-compose.yml ps
curl -sf http://localhost:5008/health | python3 -m json.tool
curl -sf http://localhost:5008/ready
```

- [ ] **Step 2: Verifikasi browser/HTTP (loloskan semua)**

| # | Cek | Harapan |
|---|---|---|
| 1 | `/health` | 200 `{"status":"healthy","database":"connected","version":"6.5.0"}` |
| 2 | `/login` | 200, form CSRF ada |
| 3 | Login `IOT_USERNAME/IOT_PASSWORD` dari `.env` | 302 → `/`, cookie HttpOnly SameSite=Lax |
| 4 | `/` (dashboard) | 200, device list rilis, auto-refresh tanpa 401 |
| 5 | `POST /api/v1/data` (device) | 200, alert dievaluasi, RFID dedup 30 dtk |
| 6 | CRUD device + regenerate key | 201/200, key plain hanya sekali |
| 7 | `/alerts`, ack + bulk-ack, `/attendance` report/export CSV | 200, CSV tanpa formula-injection |
| 8 | `POST /api/v1/system/backup` → list → download | file `iot_*.db`, `pre-restore-*` tidak terhapus otomatis |
| 9 | Chat (bila `LLM_API_KEY` diisi) `/api/v1/chat/health` | 200/offline tapi app tetap jalan |
|10 | Restart `docker compose restart nexus-iot` | restore tertunda diterapkan, session/CSRF tetap valid, health 200 lagi |

Bila `LLM_API_KEY` kosong: panel chat memang tidak tampil (bukan error) — catat sebagai pass, jangan paksa isi.

- [ ] **Step 3: Log & hygiene**

```bash
docker compose logs nexus-iot | tail -100
docker compose logs nginx | tail -50
curl -s -D - http://localhost:5008/login | grep -i -E "content-security|strict-transport|x-frame"
```

Header CSP/HSTS/X-Frame harus ada sesuai `ENABLE_HSTS`.

- [ ] **Step 4: Fixture regresi smoke**

```python
def test_deploy_smoke():
    import urllib.request
    assert urllib.request.urlopen('http://localhost:5008/health', timeout=5).status == 200
```

Run: `python3 -m pytest tests/test_refactor_deploy.py -v` (skip otomatis bila Docker tidak jalan; jangan gagalkan CI)

- [ ] **Step 5: Commit hasil verifikasi (catat hasil di CHANGELOG)**

```bash
git add tests/test_refactor_deploy.py CHANGELOG.md
git commit -m "test: docker deploy smoke + verifikasi website"
```

## Task 9: Penyelesaian — lint, test penuh, changelog

**Files:**
- Modify: `CHANGELOG.md`, `README.md` (struktur proyek + menjalankan Docker)
- Test: semua `tests/test_*.py`

- [ ] **Step 1: Lint + test penuh**

Run: `python3 -m ruff check app run.py && python3 -m pytest -q`
Expected: 0 error, 0 fail.

- [ ] **Step 2: Update docs**

`CHANGELOG.md` entri *Unreleased — Big refactor + Docker verify* (pecahan file, schema tetap v18, hasil checklist Task 8). `README.md` struktur proyek diperbarui (`app/api/`, `app/dashboards/`, `app/services/`).

- [ ] **Step 3: Final build**

Run: `docker compose -f docker-compose.yml up -d --build && curl -sf http://localhost:5008/health`
Expected: healthy.

- [ ] **Step 4: Commit**

```bash
git add CHANGELOG.md README.md
git commit -m "docs: changelog+readme pasca big refactor"
```

- [ ] **Step 5: Handoff review**

- [ ] Lampirkan: `pytest -q` tail, `ruff` tail, `docker compose ps`, `curl /health` JSON, screenshot/daftar checklist Task 8 (10 baris).
