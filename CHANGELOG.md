# Changelog

## Unreleased — AAguard rename + pembersihan

- **Rename penuh:** NEXUS → AAguard di UI, dokumentasi, logger, env (`AAGUARD_LOCK_DIR`), container/service/network Docker (`aaguard-iot`, `aaguard-nginx`, `aaguard-network`), user container (`aaguard`), dan konfigurasi Nginx (`nginx/conf.d/aaguard.conf`).
- **Dead code dihapus:** modul throttle login Flask-era, sync wrapper alert/permission, schema Pydantic tak terpakai, helper API Flask-era, health-ring JS/CSS sisa, dan template `error.html` (halaman error kini inline `_html_error`).
- **Logging file aktif:** `setup_logging()` dipanggil dari `run.py`; jika file log tidak bisa ditulis, aplikasi tetap jalan dengan log console.
- **E2E Playwright:** `tests/e2e/test_live_e2e.py` (opt-in `E2E=1`), mencakup login, metrik, navigasi section, peta, command palette, settings, logout, dan create/delete device.

## V2.0.0 — 2026-11-09

Breaking release: migrasi ke FastAPI + async + Pydantic di `app/main.py` (route `/api/v1/*` dipertahankan), hapus fitur absensi v19 (route `/cardholders`, `/attendance/*`, tabel `attendance`+`cardholders`, 5 chat tools, menu & section absensi; `DROP TABLE attendance/cardholders`), frontend ringan (lazy-load Chart.js/Leaflet, gabung CSS), port publik 4455/443 via Nginx, DB fresh (database/iot.db mulai dari nol, tanpa migrasi data lama).

- **Tanggal rilis:** 2026-11-09. Port publik Nginx `4455` + `443` (NAT `4455->443`, `${NGINX_PORT:-4455}:80` + `443:80`); DB fresh mulai dari schema v19.
- **Restore DB lama:** backup v18 (masih ada `attendance`) bila di-restore dimigrasi otomatis ke v19 (`DROP attendance/cardholders`) saat start berikutnya — aman, user tidak perlu migrasi manual (lihat README § Restore Database).
- **Rilis image:** `aaguard-iot:2.0.0` (tag Docker: `docker tag aaguard-iot:latest aaguard-iot:2.0.0`), sesuai git tag `v2.0.0`.
- **Flask dihapus:** `app/api.py`, `app/auth.py`, `app/chat.py`, `app/dashboards.py`, `app/views.py`, `app/extensions.py`, `app/ratelimit.py` dihapus; `app/__init__.py` jadi shim versi (versi tunggal di `app/main.py`); `app/database.py` tanpa Flask `g` (thread-local); `app/permissions.py` + `app/workspace.py` tanpa Flask session; auth/scope/throttle pindah ke `app/deps.py` + `app/routers/*` (FastAPI + Uvicorn, production Gunicorn + UvicornWorker). `ruff check app run.py` hijau. README disinkronkan (badge FastAPI/Uvicorn + Gunicorn 23.0.0, port publik 4455/443, tanpa baris absensi).

## Unreleased — Refactor bertahap (fondasi)

Refactor tanpa mengubah perilaku API/DB. Semua endpoint dan schema tetap sama; hanya pemisahan tanggung jawab dan pembersihan import-time side effect.

- **Config (`app/config.py`)**: helper `_env_bool/_env_int/_env_float/_env_str` terpusat; rule alert suhu diekstrak ke `_build_alert_rules()`, parser CORS ke `_parse_cors_origins()`. Nilai default dan perilaku parsing tetap sama.
- **Application factory (`app/__init__.py`)**: `create_app()` dipecah menjadi `_apply_proxy_fix`, `_init_extensions`, `_register_static_cache_bust`, `_register_blueprints`, `_register_security_headers`, `_register_error_handlers`, `_register_health_routes`. Validasi config dipindah dari import-time (`sys.exit` saat `import app`) ke `create_app()` via `validate_config_or_exit()` — import modul tidak lagi memproses exit proses.
- **Database (`app/database.py` + `app/migrations.py`)**: `database.py` 1028 baris → 132 baris (hanya koneksi + `init_db` runner). Seluruh `_migrate_v1.._migrate_v18` dan `_rebuild_fk_tables` pindah ke `app/migrations.py` + registry `MIGRATIONS`. `SCHEMA_VERSION`, `WIB_DEFAULT`, dan semua `_migrate_*` tetap bisa diimpor dari `app.database` (re-export).
- **API helpers (`app/api.py` + `app/api_common.py`)**: helper bersama (`_clean_timestamp`, `validate_device_api_key`, `update_device_status`, `_alert_label`, `_detect_interval` + konstanta `AUTO_INTERVAL_*`, `_current_user_id`, `_validate_username`, `PURGE_TABLES`, `_parse_purge_request`, `_purge_where`, `_purge_preview`) dipindah ke `app/api_common.py` (243 baris). `api.py` 3199 → 2980 baris dan mengimpor ulang semua nama tersebut, sehingga 59 route dan import lama (`from app.api import ...`, monkeypatch `app.api.get_db_context`/`sqlite3` di tes) tetap jalan.
- **Tahap berikutnya yang disarankan**: pecah route `api.py` per domain (`devices`, `alerts`, `attendance`, `users`, `system`, `ingest`) menjadi blueprint terpisah, dan ekstrak `dashboards.py` (955 baris) dengan pola yang sama.

---

## V6.5.0

Rilis yang menggabungkan perbaikan fase 1–5 (sebelumnya 6.0.0). Rincian teknis per fase ada di bagian bawah.

### Ringkasan per ID temuan

| ID | Perbaikan | Fase |
|----|-----------|------|
| N1 | Bulk Import tidak lagi selalu 500 (impor schema hilang) | 1 |
| C2 | Semua route tulis admin-only (`admin_required`) | 1 |
| C3 | Global Alert Rules dibaca mesin alert | 1 |
| C4 | Rules per device menimpa sebagian, bukan total | 1 |
| H7 | `SESSION_COOKIE_SECURE` dan HSTS mengikuti env | 1 |
| H3 | Password `.env` hanya seed admin pertama | 2 |
| N2 | Interval manual tidak ditimpa auto-detect (migrasi v15) | 2 |
| N3 | Statistik hadir hanya menghitung kartu terdaftar | 2 |
| N4 | Validasi UID RFID, ekspor CSV anti formula-injection | 2 |
| M1 | Validasi dan batas ukuran payload `/data` | 2 |
| H6 | Notifikasi Telegram aman (HTML escape + fallback) | 3 |
| H4 | Rate limit: storage dari config, kuota per device, throttle login (migrasi v16) | 3 |
| H2 | Background task: ambil alih lock + heartbeat | 3 |
| M3 | Retensi backup aman | 3 |
| H1 | Restore database diterapkan saat start | 3 |
| H5 | Timeout Nginx chat, keepalive upstream, flag Gunicorn | 3 |
| M9 | Gunicorn 23.0.0, port 5008 konsisten, compose produksi tanpa mount kode | 3 |
| M4 | Hardening AI chat | 4 |
| M7 | Logout `POST`, `/health` dan handler 500 tanpa bocor error | 4 |
| N7 | Chat disembunyikan bila LLM belum dikonfigurasi | 4 |
| C1 | Firmware membaca kredensial dari `esp32/secrets.py` (sisi kode) | 4 |
| — | Versi V6.5, tes/CI/dokumentasi (lihat Fase 5) | 5 |

### Terlihat oleh pengguna

- Versi aplikasi menjadi **6.5.0** di `/health`, `/system/info`, dan kartu **Versi Aplikasi** di UI. Sebelumnya `/system/info` menulis `4.3` secara hardcode sehingga UI menampilkan angka yang berbeda dari `/health`.
- User non-admin tidak bisa lagi mengubah/menghapus device, kartu, atau mengirim tes notifikasi (HTTP 403).
- Logout memakai `POST`; port publik default 5008; password admin hanya lewat UI setelah akun pertama dibuat.

### Fase 5 — tes, CI, dokumentasi

- **Versi** `app.__version__` = `6.5.0` sebagai satu-satunya sumber; `/system/info` kini memakainya (sebelumnya `'4.3'`). Tes `test_phase4_misc.py` tidak lagi meng-hardcode angka versi.
- **Dependensi dev** dipisah ke `requirements-dev.txt` (`-r requirements.txt`, `pytest`, `ruff`). Image Docker tetap hanya memasang `requirements.txt`; `requirements-dev.txt`, `ruff.toml`, `tests/`, `.github/` masuk `.dockerignore`.
- **Makefile** `make test` = `pytest -q`; `make lint` = `ruff check app run.py` dan tidak lagi menelan kegagalan (`2>/dev/null ||` dihapus); `make dev` memasang dependensi dev; target baru `make install-dev`.
- **CI** `.github/workflows/ci.yml`: Python 3.11, `ruff check app run.py` lalu `python -m pytest -q` pada push ke `main` dan pull request.
- **ruff.toml** hanya memilih `E9` dan `F` (kesalahan nyata: undefined name, import tak terpakai); `esp32/` dikecualikan (MicroPython).
- **README** badge versi dan Gunicorn dikoreksi (23.0.0), dokumentasi migrasi sampai v16 (`interval_manual`, `login_failures`), struktur proyek dan referensi Makefile diperbarui, catatan perilaku fase 1–4 dipindah ke bagian bernomor dalam Daftar Isi (**Kebijakan dan Perilaku Penting**), ditambah **Pengembangan dan Tes** (tes, CI, aturan versi).
- **Tes** `tests/test_phase5_release.py`: versi konsisten di kode, `/health`, `/system/info`, README, CHANGELOG; versi Gunicorn README = `requirements.txt`; pemisahan dependensi dev; isi workflow CI; target Makefile.

### Tindakan manusia (di luar kode)

1. Regenerate API key device yang pernah bocor (C1) dari dashboard dan ganti password WiFi; anggap key lama sudah bocor.
2. Bersihkan riwayat git dari kredensial lama (`git filter-repo`) dan periksa apakah repo GitHub publik.
3. Ganti `IOT_PASSWORD` dan `SECRET_KEY` di server produksi setelah fase 2 diterapkan.
4. Aktifkan HTTPS/TLS di depan Nginx bila diakses lewat jaringan yang tidak sepenuhnya tepercaya, lalu set `ENABLE_HSTS=True`.
5. Periksa `offline_timeout` di database lama (migrasi v5 memberi default 900).

### Keputusan terbuka

- Tool absensi chat (`get_present_today`, `get_absent_today`, `get_attendance_range`, `get_cardholders`) masih terbuka untuk semua user login; apakah dibatasi hanya admin?
- Chat dianggap terkonfigurasi hanya bila `LLM_API_KEY` terisi. Pengguna LLM lokal yang mengandalkan default `sk-no-key` perlu mengisi nilai apa saja.

### Temuan tambahan (belum diperbaiki)

- `make run-prod` dan contoh systemd di README menjalankan Gunicorn tanpa `--timeout`, `--graceful-timeout`, `--max-requests` seperti pada `CMD` Dockerfile.
- Lint hanya mencakup `app` dan `run.py`; folder `tests/` belum dilint.

---

## Rincian per fase

## Fase 1 — perbaikan cepat
- **N1** Bulk Import tidak lagi selalu 500: `bulk_import_item_schema` kini diimpor. Target `make lint` ditambahkan agar `undefined name` tertangkap.
- **C2** Semua route tulis (device, regenerate-key, alert-rules per device, bulk-import, cardholders, tes notifikasi) admin-only lewat decorator `admin_required`; pola `_require_admin()` dihapus. Kontrol terkait disembunyikan untuk non-admin di UI desktop dan mobile.
- **C3** Global Alert Rules tersimpan kini dibaca mesin alert (cache TTL 45 dtk, di-invalidate saat PUT/DELETE; JSON korup -> default).
- **C4** Rules per device menimpa global per sensor, bukan mengganti total.
- **H7** `SESSION_COOKIE_SECURE` tidak lagi dipaksa `True` di production (ikut env, default = `ENABLE_HSTS`); HSTS hanya bila `ENABLE_HSTS=True`; peringatan log bila production memakai cookie non-Secure.

## Fase 2 — autentikasi dan data
- **H3** Password `.env` hanya seed admin pertama (tabel users kosong); login selalu lewat `check_password_hash`; hash tidak lagi ditimpa password `.env`.
- **N2** Migrasi v15 menambah `devices.interval_manual`. Interval yang diisi manual tidak ditimpa auto-detect; auto-detect butuh >=5 sampel, abaikan selisih <2 dtk, minimum 10 dtk, hanya menulis bila berubah >20%. Mengosongkan field edit = kembali otomatis.
- **N3** `hadir_hari_ini` hanya menghitung UID terdaftar (kartu asing tetap di `kartu_belum_terdaftar`).
- **N4** UID RFID divalidasi (hex 4-32, boleh `0x`) di `/data` dan `POST /cardholders`; ekspor CSV memakai `csv_safe`.
- **M1** Batas body `/data` (`DATA_MAX_BYTES`, 413), `data` harus dict datar dengan key/nilai tervalidasi, `sensor_type` berpola.

## Fase 3 — keandalan operasional
- **H6** Notifikasi Telegram memakai `parse_mode=HTML` dengan `html.escape` pada semua nilai dinamis; bila Telegram menjawab 400 "can't parse entities", dikirim ulang sebagai teks polos. Teks exception requests tidak lagi di-log (URL memuat token).
- **H4** `Limiter` memakai `RATE_LIMIT_STORAGE` dari config; peringatan bila `memory://` dipakai dengan >1 worker (`WEB_CONCURRENCY`). Kuota `/data` per `device_id` (fallback IP, key function tidak pernah raise) + plafon per IP `RATE_LIMIT_DATA_IP`. Login: throttle kegagalan per username+IP dan per IP, disimpan di DB (migrasi v16, tabel `login_failures`); limit lama tidak dilemahkan.
- **H2** Worker yang tidak mendapat lock background kini mencoba ulang tiap 30 detik dan mengambil alih bila pemilik mati. Heartbeat tiap task di `user_settings` (`bg_hb_*`), tampil di `/system/info` → `background` dengan penanda `stale` (>3× interval). File lock tidak lagi ter-truncate oleh worker yang gagal mengunci.
- **M3** Retensi backup hanya menghapus `iot_*.db`, selalu menyisakan `BACKUP_MIN_KEEP` (default 3) terbaru, tidak pernah menghapus `pre-restore-*.db`. Backup pertama dibuat ~30 detik setelah start bila belum ada backup yang cukup baru. Nama backup memakai waktu WIB.
- **H1** Restore tidak lagi menimpa DB hidup: endpoint menyiapkan `<DB>.restore-pending` + `<DB>.restore-marker`; diterapkan saat start (hapus `-wal`/`-shm`, ganti DB, hapus penanda), ditunda bila DB masih dipakai proses lain.
- **H5** Nginx: `proxy_read_timeout 180s` untuk `/api/v1/chat`; header `Connection` lewat `map` + `upstream` keepalive. Gunicorn: `--timeout 60 --graceful-timeout 30 --max-requests 1000 --max-requests-jitter 100`, worker dari `WEB_CONCURRENCY`.
- **M9** `gunicorn` 21.2.0 → 23.0.0 (CVE-2024-1135). Port publik disamakan ke 5008 (`.env.example`, `CORS_ORIGINS`, compose, README, firmware). Mount kode dipindah dari `docker-compose.yml` ke `docker-compose.override.yml` (dev); `make docker-up` = produksi, `make docker-dev-up` = dev.

## Fase 4 — AI chat dan hal sedang
- **M4** Chat dikeraskan: hanya role `user`/`assistant` dengan `content` string yang diteruskan ke LLM (field lain dibuang), pesan dipotong ke 4000 karakter, maksimum 10 pesan. Hasil tool dibatasi 100 baris / 20 KB (`truncated: true`). Hingga 3 putaran tool (maks 5 panggilan per putaran). Error tool/LLM tidak lagi membocorkan `str(e)` atau URL endpoint; status HTTP upstream kini tampil benar (sebelumnya selalu `?` karena `Response` bernilai False untuk 4xx/5xx). System prompt menandai isi data sebagai data, bukan instruksi. Tool absensi **tetap** terbuka untuk semua user login (keputusan terbuka, lihat di bawah).
- **M7** Logout kini `POST` + CSRF (tombol desktop dan mobile memakai `fetch`); `GET /logout` hanya redirect ke login tanpa menghapus sesi. `/health` memakai konstanta `app.__version__` (6.0.0) dan tidak menampilkan `str(e)` saat gagal. Handler 500 di `api.py` (global alert rules PUT/DELETE, backup, daftar backup, cleanup, tes notifikasi, tes channel, restore) mengembalikan pesan generik; detail ke log.
- **N7** Bila `LLM_API_KEY` kosong: `/api/v1/chat/health` menjawab 200 `{configured:false}`, `POST /api/v1/chat` menjawab 503, dan tombol topbar, FAB mobile, panel, serta `chat.js` tidak dirender (tidak ada polling 503).
- **C1 (sisi kode)** Firmware membaca `WIFI_SSID`, `WIFI_PASSWORD`, `API_URL`, `DEVICE_ID`, `API_KEY` dari `esp32/secrets.py` (di-ignore git); `esp32/secrets.example.py` berisi placeholder. Rotasi key dan pembersihan riwayat git tetap dilakukan manusia.
- Kebersihan: import tak terpakai dihapus (`signal`, `logging` di `app/__init__.py`; `timedelta` di `alerts.py`; `_ConfigClass` di `api.py`; `os`, `logging` di `run.py`).

### Keputusan terbuka (fase 4)
- Apakah tool absensi chat (`get_present_today`, `get_absent_today`, `get_attendance_range`, `get_cardholders`) dibatasi hanya untuk admin? Belum diubah.
- Chat dianggap terkonfigurasi hanya bila `LLM_API_KEY` terisi (sesuai N7). Pengguna LLM lokal yang selama ini mengandalkan default `sk-no-key` perlu mengisi nilai apa saja.


## Perbaikan Pascabedah (Fase A)

Dari hasil audit kode + verifikasi di staging (2026-10-19).

### Diperbaiki

| Area | Perbaikan |
|---|---|
| Manage user | Modal legacy dihapus. `settings_section.html` dan `modals.html` sama-sama merender 7 `id` form yang sama, sehingga `getElementById()` menulis ke drawer Pengaturan dan Command Palette → "Kelola user" selalu gagal. Sekarang satu-satunya pintu masuk `AAGuardUsers.open()`. |
| Notifikasi | `POST /api/v1/notifications/test` melaporkan `success: true` walau tidak ada channel aktif (`all([])` atas generator kosong). Kini menyaring kunci `_` lebih dulu dan membalas 503 bila memang belum siap. |
| AAguard AI | Menu, panel, dan `chat.js` hilang total saat `LLM_API_KEY` kosong. Menu kini tetap terlihat dengan status "belum aktif" + penjelasan cara mengaktifkannya. |
| Mobile | `historyChartMobile is not defined` setiap ganti tema. |
| Markup | `</nav>` ganda di `dashboard.html`. |
| Test | 5 test failure → 0. `PYTHON_DOTENV_DISABLED=1` di `conftest.py` membuat test hermetik terhadap `.env` sungguhan; `importlib.reload(app.extensions)` kini memulihkan singleton `limiter` sehingga tidak merusak test lain. |

### Diketahui masih terbuka (Fase B/C)

Severity alert memakai pita "first match" sehingga 39 °C dilabeli `danger` dan pesannya masih menyebut pita *healthy*. Validasi `offline_timeout` belum dipakai pada `POST /devices` dan bulk-import. `PUT /dashboards/<id>/layout` belum divalidasi per-elemen. Backup `pre-delete_*`/`pre-restore_*` tidak pernah di-prune. Hapus dashboard diam-diam menghapus kartu absensi. Session idle timeout tidak pernah aktif karena `/api/v1/metrics` belum terdaftar sebagai polling.

## Perbaikan Pascabedah (Fase B)

Dead code + logika backend. Baseline test: 323 lulus → 335 lulus, 0 gagal.

### Diperbaiki

| Area | Perbaikan |
|---|---|
| Mesin alert | `SEVERITY_ORDER` kini memuat `info`, jadi rule info-only tidak lagi dilaporkan `danger`. Pesan alert memakai band bersarang untuk menyebut batas yang benar-benar dilanggar: 36 °C → "Melewati batas warning (32°C)", bukan lagi "Di luar batas normal (6–28°C)". Validasi rule disatukan ke `utils.validate_single_alert_rule` (termasuk `min <= max`). |
| `offline_timeout` | `OfflineTimeoutField` dipakai di POST/PUT/bulk-import (10–604800 detik) plus syarat ≥ `expected_interval`. Sebelumnya POST menerima `-5`. |
| Hapus dashboard | Dashboard yang masih berisi kartu RFID ditolak 409 — sebelumnya kartu + riwayat absensi terhapus diam-diam. |
| `PUT /layout` | Elemen non-dict ditolak 400 (sebelumnya 500). |
| Hapus user | Ditolak bila admin pelaku tidak punya dashboard tujuan, supaya device/kartu tidak jadi yatim. |
| Backup | `pre-delete_*` dan `pre-restore_*` ikut di-prune (file manual tetap aman). Sebelumnya menumpuk selamanya. |
| Session | `/api/v1/metrics` dan `/api/v1/chat` didaftarkan sebagai polling agar idle timeout benar-benar aktif. |
| Restore | `_db_in_use()` membedakan `database is locked` (True) dari DB rusak (False) — restore tidak lagi ditolak selamanya saat DB korup. |
| Halaman error | 404/401/403/429/500 untuk route halaman dirender inline oleh `_html_error`; endpoint `/api/*` tetap JSON. |
| Dead code | `app/decorators.py`, `role_required`, `can_access_dashboard`, `default_dashboard_for_admin`, route `/alerts` + template, dan sisa JS/CSS untuk id yang tidak ada (`mapPreview`, `pageTitle`, `mapListCount`, `alertFilterInfo`, `chatTab`, `updateJsonPreview`) dihapus. |

### Diketahui masih terbuka (Fase C)

`PUT /dashboards/<id>/layout` belum dipanggil frontend (layout masih localStorage). 8 method `API.*` dan `dashboard_store.js` belum dikonsolidasikan. Dedup notifikasi masih per-proses.
