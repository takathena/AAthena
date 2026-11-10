# AAguard IoT Platform

Platform monitoring IoT real-time untuk perangkat ESP32, ESP8266, Arduino, dan Raspberry Pi. Menyediakan dashboard web, peta interaktif, analitik multi-chart yang bisa di-drag, sistem alert berjenjang dengan notifikasi Telegram, dan asisten AI yang terhubung langsung ke database.

![Version](https://img.shields.io/badge/version-2.0.0-blue?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.162.2-009688?style=flat-square&logo=fastapi&logoColor=white)
![Uvicorn](https://img.shields.io/badge/Uvicorn-0.54.0-499848?style=flat-square&logo=uvicorn&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-WAL-003B57?style=flat-square&logo=sqlite&logoColor=white)
![Gunicorn](https://img.shields.io/badge/Gunicorn-23.0.0-499848?style=flat-square&logo=gunicorn&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-compose-2496ED?style=flat-square&logo=docker&logoColor=white)
![Nginx](https://img.shields.io/badge/Nginx-alpine-009639?style=flat-square&logo=nginx&logoColor=white)
![Chart.js](https://img.shields.io/badge/Chart.js-4.4.0-FF6384?style=flat-square&logo=chartdotjs&logoColor=white)
![Leaflet](https://img.shields.io/badge/Leaflet-1.9.4-199900?style=flat-square&logo=leaflet&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)

---

## Daftar Isi

1. [Ringkasan](#ringkasan)
2. [Fitur](#fitur)
3. [Tech Stack](#tech-stack)
4. [Arsitektur](#arsitektur)
5. [Persyaratan Sistem](#persyaratan-sistem)
6. [Instalasi](#instalasi)
7. [Konfigurasi Environment](#konfigurasi-environment)
8. [Setup Perangkat ESP32](#setup-perangkat-esp32)
9. [Referensi API](#referensi-api)
10. [Struktur Proyek](#struktur-proyek)
11. [Sistem Alert](#sistem-alert)
12. [Multi-User dan Dashboard](#multi-user-dan-dashboard)
13. [AAguard AI Chat](#aaguard-ai-chat)
14. [Background Tasks](#background-tasks)
15. [Database dan Migrations](#database-dan-migrations)
16. [Deployment Produksi](#deployment-produksi)
17. [Makefile Reference](#makefile-reference)
18. [Keamanan](#keamanan)
19. [Troubleshooting](#troubleshooting)
20. [Kebijakan dan Perilaku Penting](#kebijakan-dan-perilaku-penting)
21. [Pengembangan dan Tes](#pengembangan-dan-tes)
22. [Lisensi](#lisensi)

---

## Ringkasan

AAguard adalah aplikasi server tunggal yang menerima data sensor dari perangkat IoT melalui HTTP POST, menyimpannya di SQLite (mode WAL), lalu menyajikannya lewat dashboard web dan API JSON. Sistem mendukung banyak pengguna, banyak dashboard per pengguna, banyak tab analitik per dashboard, dan layout chart yang dapat diatur bebas oleh pengguna (drag dan resize).

Dirancang untuk berjalan di lingkungan produksi: FastAPI + Uvicorn (Gunicorn multi-worker dengan UvicornWorker), Nginx sebagai reverse proxy, Docker Compose, rate limiting, CSRF protection, hashing API key, background task terkoordinasi via file lock, auto-backup database, dan retensi data per kategori.

---

## Fitur

### Monitoring dan Visualisasi

- Dashboard real-time dengan auto-refresh 30 detik, kartu metrik, dan activity feed
- Peta interaktif berbasis Leaflet dengan marker cluster, filter status, dan pencarian
- Editor lokasi device drag-and-drop langsung di peta
- Analitik multi-chart: line, bar, area, doughnut, pie, polar area, radar, horizontal bar, stacked bar, dan stacked area
- Layout chart bebas: drag dari header, resize dari sudut kanan bawah, resize tinggi kanvas dari handle bawah
- Time range global: 5 menit hingga 30 hari
- Multi-tab analitik per dashboard
- Preview chart di tab lain tanpa reload

### Alert System

- State machine berjenjang: healthy -> warning -> danger -> warning -> healthy
- Hysteresis per sensor untuk mencegah alert flip-flop di sekitar batas
- Threshold global dan override per device
- Acknowledgment dengan severity-aware re-trigger: alert baru hanya di-trigger lagi jika severity memburuk
- Offline detection otomatis dengan timeout = 2x interval kirim
- Auto-detect interval kirim dari median delta 5 data terakhir
- Riwayat lengkap (created, severity_changed, cleared, acknowledged)
- Bulk acknowledge dan mark-all-visible
- Notifikasi Telegram dengan deduplikasi 60 detik dan retry 3x

### Multi-User

- Autentikasi session dengan idle timeout terpisah dari lifetime
- Setiap pengguna punya dashboard sendiri
- Composite unique constraint pada (user_id, slug)
- Auto-create dashboard saat login pertama

### AAguard AI

- Chat panel terintegrasi yang bisa minimize
- Mendukung endpoint OpenAI-compatible (OpenRouter, Ollama, vLLM, Hermes)
- Function calling dengan 4 tool yang query langsung ke database
- Markdown rendering dengan subset aman (XSS-protected)
- Health check upstream LLM otomatis

### Operasional

- Auto-backup database SQLite tiap 24 jam
- Retensi data per kategori: sensor 30d, history 90d, status log 30d
- VACUUM otomatis jika cleanup menghapus lebih dari 1000 baris
- Rotating log file dengan batas 10 MB x 5 file
- Background task hanya dijalankan oleh satu worker via file lock
- Health endpoint dan readiness endpoint

---

## Tech Stack

| Layer | Teknologi | Versi |
|-------|-----------|-------|
| Bahasa | Python | 3.11 |
| Web Framework | FastAPI | 0.162.2 |
| WSGI Server | Gunicorn | 23.0.0 |
| ASGI Server | Uvicorn | 0.54.0 |
| Database | SQLite (WAL mode) | Bawaan Python 3.11 |
| Templating | Jinja2 (via FastAPI) | 3.1.6 |
| Form / CSRF | Starlette Session + CSRF double-submit | 1.10.0 |
| Rate Limiting | SlowAPI | 0.1.10 |
| CORS | Starlette CORSMiddleware | 1.10.0 |
| Validasi | Pydantic | 2.14.3 |
| HTTP Client | Requests | 2.32.3 |
| Config Loader | python-dotenv | 1.2.3 |
| WSGI Utilities | Werkzeug | 3.1.8 |
| Signing | itsdangerous | 2.2.0 |
| Templating Support | MarkupSafe | 3.0.3 |
| CLI | Click | 8.5.0 |
| Event Signals | blinker | 1.9.0 |
| Chart Library | Chart.js | 4.4.0 |
| Peta | Leaflet | 1.9.4 |
| Marker Cluster | Leaflet.markercluster | 1.5.3 |
| Drag / Resize | interact.js | 1.10.27 |
| Icons | Font Awesome Free | 6.5.1 |
| Font | Geist / Geist Mono | Google Fonts |
| Container | Docker | Multi-stage |
| Container Orchestration | Docker Compose | v2 |
| Reverse Proxy | Nginx | Alpine |
| Firmware Runtime | MicroPython | ESP32 / ESP8266 |

---

## Arsitektur

```
                    +-------------------+
                    |   ESP32           |
                    |   (HTTP POST)     |
                    +---------+---------+
                              |
                              v
                    +---------+---------+
                    |   Nginx :4455/:443  |
                    |  (reverse proxy)  |
                    +---------+---------+
                              |
                              v
                    +---------+---------+
                    | FastAPI + Uvicorn   |
                    |    :5000          |
                    +----+---------+----+
                         |         |
              +----------+         +-----------+
              |                                |
              v                                v
      +-------+--------+              +--------+--------+
      | SQLite WAL     |              | Static / API    |
      | iot.db         |              | untuk browser   |
      +----------------+              +-----------------+
              ^
              |
      +-------+------------------+
      | Background workers       |
      | (via file lock)          |
      | - status checker         |
      | - data cleanup           |
      | - db backup              |
      +--------------------------+
```

Alur request:

1. Perangkat mengirim JSON ke `POST /api/v1/data` dengan `device_id` dan `api_key`.
2. Server memverifikasi API key (SHA-256 hash, timing-safe compare).
3. Data disimpan ke `sensor_data`, status device di-set online, dan interval kirim di-auto-detect.
4. Alert rules dievaluasi terhadap data sensor, dan jika perlu alert dibuat atau diupdate.
5. Background worker (hanya satu dari N worker) memeriksa device offline tiap `CHECK_INTERVAL` detik.
6. Browser mengakses dashboard, yang memanggil API via fetch dengan CSRF token.

---

## Persyaratan Sistem

### Untuk deployment Docker (direkomendasikan)

- Docker Engine 20.10 atau lebih baru
- Docker Compose v2
- Port 4455 (atau `NGINX_PORT` yang di-set) dan 443 tersedia
- Minimal 512 MB RAM, 1 GB disarankan
- Minimal 500 MB disk untuk aplikasi + ruang untuk database dan backup

### Untuk deployment manual

- Python 3.11 atau lebih baru
- pip dan venv
- SQLite 3.35 atau lebih baru (WAL mode dengan window function)
- Sistem operasi Linux, macOS, atau WSL
- Port 5000 tersedia

### Untuk perangkat ESP32

- ESP32 atau ESP8266 dengan MicroPython terinstall
- Sensor DHT22 atau sensor lain yang didukung
- Koneksi WiFi stabil
- `urequests` dan `ujson` tersedia (biasanya sudah ada di MicroPython standar)

---

## Instalasi

### Docker (Direkomendasikan)

```bash
git clone https://github.com/takathena/AAthena.git
cd AAthena

cp .env.example .env
nano .env
```

Isi minimal `SECRET_KEY` dan `IOT_PASSWORD`:

```bash
# Generate SECRET_KEY
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Set juga `IOT_PASSWORD` dengan password yang kuat (minimal 8 karakter, jangan pakai `admin` atau `password`).

```bash
mkdir -p database logs backup
chown -R 1000:1000 database logs backup

docker compose up -d --build
```

Akses di `http://localhost:4455`.

Cek status container:

```bash
docker compose ps
docker compose logs -f aaguard-iot
```

### Manual (Development)

```bash
git clone https://github.com/takathena/AAthena.git
cd AAthena

make dev
nano .env
make run
```

Atau tanpa Makefile:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
mkdir -p database logs backup
python run.py
```

Akses di `http://localhost:5000`.

---

## Konfigurasi Environment

Semua variabel dibaca dari file `.env` di root proyek. Nilai default ada di `app/config.py`.

### Server

| Variabel | Default | Deskripsi |
|----------|---------|-----------|
| `HOST` | `0.0.0.0` | Bind address FastAPI |
| `PORT` | `5000` | Port internal FastAPI/uvicorn (di Docker tetap 5000, Nginx meneruskan ke sini) |
| `DEBUG` | `False` | Mode debug FastAPI/uvicorn |
| `NGINX_PORT` | `4455` | Port publik Nginx (HTTP). Dashboard dan firmware ESP32 mengakses lewat port ini; HTTPS di `443` |
| `WEB_CONCURRENCY` | `2` | Jumlah worker Gunicorn (Docker). Dibaca Gunicorn dan dipakai untuk peringatan rate limit |

### Keamanan

| Variabel | Default | Deskripsi |
|----------|---------|-----------|
| `SECRET_KEY` | (wajib) | 64 karakter hex, untuk signing session dan CSRF |
| `SESSION_COOKIE_SECURE` | ikut `ENABLE_HSTS` | `True` = cookie hanya via HTTPS. Tidak lagi dipaksa `True` di production; `False` memungkinkan login via `http://<IP-LAN>` (hanya jaringan tepercaya). Peringatan dicatat di log bila production memakai `False` |
| `SESSION_LIFETIME_HOURS` | `24` | Umur absolut session |
| `SESSION_IDLE_TIMEOUT_MINUTES` | `120` | Timeout idle (tidak termasuk polling API) |
| `MAX_CONTENT_LENGTH` | `2097152` | Ukuran payload maksimum (byte) |
| `ENABLE_HSTS` | `False` | Aktifkan HSTS header, hanya jika HTTPS |
| `CSP_REPORT_ONLY` | `False` | Mode CSP report-only untuk debugging |

### CSP Overrides

Semua opsional. Kalau tidak diisi, pakai default dari `app/config.py`.

| Variabel | Keterangan |
|----------|------------|
| `CSP_SCRIPT_SRC` | Sumber script yang diizinkan |
| `CSP_STYLE_SRC` | Sumber stylesheet yang diizinkan |
| `CSP_FONT_SRC` | Sumber font yang diizinkan |
| `CSP_IMG_SRC` | Sumber gambar yang diizinkan |
| `CSP_CONNECT_SRC` | Sumber koneksi (fetch, XHR, WebSocket) |

### Autentikasi

| Variabel | Default | Deskripsi |
|----------|---------|-----------|
| `IOT_USERNAME` | `admin` | Username admin awal |
| `IOT_PASSWORD` | (wajib) | Password admin awal, min 8 karakter |

### Database

| Variabel | Default | Deskripsi |
|----------|---------|-----------|
| `DB_PATH` | `database/iot.db` | Path file SQLite |
| `DATA_RETENTION_DAYS` | `30` | Retensi data sensor |
| `ALERT_HISTORY_RETENTION_DAYS` | `90` | Retensi riwayat alert |
| `STATUS_LOG_RETENTION_DAYS` | `30` | Retensi log status device |

### Backup

| Variabel | Default | Deskripsi |
|----------|---------|-----------|
| `BACKUP_ENABLED` | `True` | Aktifkan auto-backup |
| `BACKUP_INTERVAL_HOURS` | `24` | Interval backup |
| `BACKUP_RETENTION_DAYS` | `7` | Retensi file backup otomatis `iot_*.db` |
| `BACKUP_MIN_KEEP` | `3` | Jumlah backup `iot_*.db` terbaru yang selalu disimpan walau lewat retensi |
| `BACKUP_DIR` | `backup` | Direktori backup |

### Device Monitoring

| Variabel | Default | Deskripsi |
|----------|---------|-----------|
| `OFFLINE_TIMEOUT` | `900` | Fallback timeout offline (detik) |
| `CHECK_INTERVAL` | `60` | Interval pengecekan status (detik) |
| `DEFAULT_EXPECTED_INTERVAL` | `60` | Interval kirim default |
| `DEFAULT_OFFLINE_SEVERITY` | `danger` | Severity alert offline default |
| `BACKGROUND_TASKS_ENABLED` | `True` | Aktifkan background worker |

### CORS

| Variabel | Default | Deskripsi |
|----------|---------|-----------|
| `CORS_ORIGINS` | `http://localhost:5000` (contoh `.env.example`: `http://localhost:4455`) | Origin yang diizinkan, pisah dengan koma. `*` ditolak |

### Rate Limiting

| Variabel | Default | Deskripsi |
|----------|---------|-----------|
| `RATE_LIMIT_DEFAULT` | `200 per minute` | Limit umum untuk endpoint API |
| `RATE_LIMIT_DATA` | `60 per minute` | Limit endpoint `/data`, dihitung **per `device_id`** (dari body JSON); jatuh ke IP bila body tidak valid |
| `RATE_LIMIT_DATA_IP` | `600 per minute` | Plafon per IP untuk `/data` (mencegah rotasi `device_id` palsu) |
| `RATE_LIMIT_LOGIN` | `5 per minute` | Limit endpoint login |
| `RATE_LIMIT_REGENERATE` | `10 per minute` | Limit regenerate API key |
| `RATE_LIMIT_STORAGE` | `memory://` | Storage backend Limiter (dibaca dari config, mis. `redis://host:6379/0`) |
| `LOGIN_MAX_FAILURES` | `5` | Kegagalan login per kombinasi username+IP sebelum dikunci |
| `LOGIN_IP_MAX_FAILURES` | `20` | Kegagalan login per IP (semua username) sebelum IP dikunci |
| `LOGIN_FAIL_WINDOW_SECONDS` | `900` | Jendela penghitungan kegagalan |
| `LOGIN_LOCKOUT_SECONDS` | `900` | Lama penguncian |

Catatan: `memory://` tidak shared antar worker Gunicorn; aplikasi mencatat peringatan saat start bila `memory://` dipakai dengan `WEB_CONCURRENCY` > 1. Untuk deployment multi-worker produksi, gunakan `redis://` atau `memcached://`. Penghitung login gagal disimpan di database (tabel `login_failures`), jadi tetap konsisten antar worker tanpa Redis.

### Logging

| Variabel | Default | Deskripsi |
|----------|---------|-----------|
| `LOG_LEVEL` | `INFO` | Level log |
| `LOG_FILE` | `logs/aaguard.log` | Path dasar file log; tiap worker menulis `logs/aaguard.log.<pid>` |
| `LOG_MAX_BYTES` | `10485760` | Ukuran maksimum per file log |
| `LOG_BACKUP_COUNT` | `5` | Jumlah file log yang disimpan |

### Alert Threshold Suhu

Hanya suhu yang bisa di-override via env. Sensor lain pakai default dari `app/config.py::ALERT_RULES`.

| Variabel | Default | Keterangan |
|----------|---------|------------|
| `ALERT_TEMP_HEALTHY_MIN` | `6` | Batas bawah healthy |
| `ALERT_TEMP_HEALTHY_MAX` | `28` | Batas atas healthy |
| `ALERT_TEMP_WARNING_MIN` | `0` | Batas bawah warning |
| `ALERT_TEMP_WARNING_MAX` | `32` | Batas atas warning |
| `ALERT_TEMP_DANGER_MIN` | `-10` | Batas bawah danger |
| `ALERT_TEMP_DANGER_MAX` | `40` | Batas atas danger |

### Notifikasi Telegram

| Variabel | Default | Deskripsi |
|----------|---------|-----------|
| `NOTIFY_ENABLED` | `False` | Aktifkan notifikasi |
| `NOTIFY_MIN_SEVERITY` | `warning` | Severity minimum untuk dikirim |
| `NOTIFY_ON_CLEARED` | `True` | Kirim notifikasi saat alert selesai |
| `TELEGRAM_ENABLED` | `False` | Aktifkan channel Telegram |
| `TELEGRAM_BOT_TOKEN` | (kosong) | Token bot dari BotFather |
| `TELEGRAM_CHAT_ID` | (kosong) | Chat ID tujuan |

Jika `NOTIFY_ENABLED=True` maka `TELEGRAM_ENABLED` harus `True` dan token serta chat ID wajib diisi, kalau tidak aplikasi akan gagal start.

### AAguard AI Chat

| Variabel | Default | Deskripsi |
|----------|---------|-----------|
| `LLM_BASE_URL` | `http://localhost:8000/v1` | Base URL endpoint OpenAI-compatible |
| `LLM_API_KEY` | _(kosong)_ | API key endpoint. **Kosong = fitur chat nonaktif** (tombol/panel chat tidak ditampilkan). Untuk Ollama/vLLM lokal isi nilai apa saja, mis. `sk-no-key` |
| `LLM_MODEL` | `nvidia/nemotron-3-super-120b-a12b:free` | Nama model |
| `LLM_TIMEOUT` | `120` | Timeout request (detik) |

### File Lock

| Variabel | Default | Deskripsi |
|----------|---------|-----------|
| `AAGUARD_LOCK_DIR` | `/tmp` | Direktori lock file untuk koordinasi background task |

Pada deployment multi-container, `AAGUARD_LOCK_DIR` harus menunjuk ke volume yang di-share antar-worker, atau cukup satu container yang menjalankan background task (default).

---

## Setup Perangkat ESP32

1. Login ke dashboard, klik menu Perangkat, klik Tambah.
2. Isi Device ID, Nama, Tipe, dan Lokasi.
3. Catat API key yang muncul. API key hanya ditampilkan satu kali.
4. Salin `esp32/secrets.example.py` menjadi `esp32/secrets.py` lalu isi kredensial. File ini **tidak di-commit** (ada di `.gitignore`); `main.py` hanya membacanya:

```python
WIFI_SSID = "NamaWiFi"
WIFI_PASSWORD = "PasswordWiFi"
API_URL = "http://IP-SERVER:4455/api/v1/data"   # port Nginx (NGINX_PORT); 5000 hanya jika menjalankan FastAPI langsung
DEVICE_ID = "ESP32-001"
API_KEY = "api-key-dari-dashboard"
```

   Pengaturan non-rahasia (`SENSOR_TYPE`, `DHT_PIN`, `SEND_INTERVAL`, `TIMEZONE_OFFSET`) tetap di `esp32/main.py`.

5. Upload keduanya ke ESP32 dengan ampy:

```bash
pip install adafruit-ampy
ampy --port /dev/ttyUSB0 put esp32/main.py
ampy --port /dev/ttyUSB0 put esp32/secrets.py
ampy --port /dev/ttyUSB0 reset
```

6. Monitor via serial:

```bash
screen /dev/ttyUSB0 115200
```

### Format Payload

```json
{
  "device_id": "ESP32-001",
  "api_key": "your-api-key",
  "sensor_type": "DHT22",
  "wifi_ssid": "NamaWiFi",
  "uptime_seconds": 3600,
  "data": {
    "temperature": 25.5,
    "humidity": 60.0
  }
}
```

### Contoh dengan curl

```bash
curl -X POST http://localhost:4455/api/v1/data   # via Nginx; dev langsung ke FastAPI: :5000 \
  -H "Content-Type: application/json" \
  -d '{
    "device_id": "ESP32-001",
    "api_key": "your-api-key",
    "sensor_type": "DHT22",
    "data": {"temperature": 25.5, "humidity": 60.0}
  }'
```

### Sensor yang Didukung Alert

| Key | Label | Unit | Rentang Default (healthy) |
|-----|-------|------|---------------------------|
| `temperature` | Suhu | °C | 6 - 28 |
| `humidity` | Kelembaban | % | 20 - 90 |
| `gas_level` | Level Gas | ppm | 0 - 70 |
| `moisture` | Kelembaban Tanah | % | 40 - 70 |
| `lux` | Cahaya | lux | 100 - 800 |
| `co2` | CO2 | ppm | 300 - 1000 |
| `smoke` | Asap | ppm | 0 - 200 |
| `voc` | VOC | ppb | 0 - 250 |
| `air_quality` | Kualitas Udara | AQI | 0 - 100 |
| `motion` | Gerakan | - | 0 - 0 |

---

## Referensi API

Semua endpoint API diawali `/api/v1`. Autentikasi session menggunakan cookie, autentikasi device menggunakan `api_key` di payload.

### Device (Public)

| Method | Endpoint | Auth | Keterangan |
|--------|----------|------|------------|
| POST | `/api/v1/data` | API key | Terima data dari device |

### Devices

| Method | Endpoint | Auth | Keterangan |
|--------|----------|------|------------|
| GET | `/api/v1/devices` | Session | List device dengan pagination |
| POST | `/api/v1/devices` | Session | Tambah device baru |
| GET | `/api/v1/devices/<id>` | Session | Detail device |
| PUT | `/api/v1/devices/<id>` | Session | Update device |
| DELETE | `/api/v1/devices/<id>` | Session | Hapus device dan semua data terkait |
| GET | `/api/v1/devices/<id>/history` | Session | Riwayat sensor |
| GET | `/api/v1/devices/<id>/status-history` | Session | Riwayat perubahan status |
| GET | `/api/v1/devices/<id>/export` | Session | Export CSV atau JSON |
| POST | `/api/v1/devices/<id>/regenerate-key` | Session | Regenerate API key |
| GET | `/api/v1/devices/<id>/alert-rules` | Session | Ambil alert rules device |
| PUT | `/api/v1/devices/<id>/alert-rules` | Session | Update alert rules |
| DELETE | `/api/v1/devices/<id>/alert-rules` | Session | Reset ke global |

### Dashboard

| Method | Endpoint | Auth | Keterangan |
|--------|----------|------|------------|
| GET | `/api/v1/dashboard` | Session | Data summary + list device |
| GET | `/api/v1/dashboards` | Session | List dashboard user |
| POST | `/api/v1/dashboards` | Session | Buat dashboard baru |
| GET | `/api/v1/dashboards/<id>` | Session | Detail dashboard + widget |
| PUT | `/api/v1/dashboards/<id>` | Session | Update dashboard |
| DELETE | `/api/v1/dashboards/<id>` | Session | Hapus dashboard |
| GET | `/api/v1/dashboards/slug/<slug>` | Session | Detail dashboard by slug |
| POST | `/api/v1/dashboards/<id>/set-default` | Session | Set sebagai default |
| PUT | `/api/v1/dashboards/<id>/layout` | Session | Simpan posisi dan ukuran widget |

### Analytics Tabs dan Widgets

| Method | Endpoint | Auth | Keterangan |
|--------|----------|------|------------|
| GET | `/api/v1/dashboards/<id>/analytics-tabs` | Session | List tab |
| POST | `/api/v1/dashboards/<id>/analytics-tabs` | Session | Buat tab |
| PUT | `/api/v1/analytics-tabs/<id>` | Session | Update tab |
| DELETE | `/api/v1/analytics-tabs/<id>` | Session | Hapus tab |
| GET | `/api/v1/dashboards/<id>/analytics-tabs/<tab>/widgets` | Session | List widget di tab |
| POST | `/api/v1/dashboards/<id>/widgets` | Session | Buat widget |
| PUT | `/api/v1/widgets/<id>` | Session | Update widget |
| DELETE | `/api/v1/widgets/<id>` | Session | Hapus widget |

### Alerts

| Method | Endpoint | Auth | Keterangan |
|--------|----------|------|------------|
| GET | `/api/v1/alerts` | Session | List alert aktif |
| GET | `/api/v1/alerts/all` | Session | List alert gabungan dengan filter |
| GET | `/api/v1/alerts/history` | Session | Riwayat alert |
| GET | `/api/v1/alerts/stats` | Session | Statistik alert |
| GET | `/api/v1/alerts/trend` | Session | Trend alert per jam |
| POST | `/api/v1/alerts/<id>/acknowledge` | Session | Acknowledge satu alert |
| POST | `/api/v1/alerts/bulk-acknowledge` | Session | Acknowledge banyak alert |

Filter untuk `/api/v1/alerts/all`:

- `status`: `all`, `active`, atau `resolved`
- `severity`: `danger`, `warning`, `info`
- `device_id`: string
- `limit`: integer, maksimum 1000

### Chat AI

| Method | Endpoint | Auth | Keterangan |
|--------|----------|------|------------|
| POST | `/api/v1/chat` | Session | Kirim pesan ke LLM |
| GET | `/api/v1/chat/health` | Session | Cek status upstream LLM |

### System

| Method | Endpoint | Auth | Keterangan |
|--------|----------|------|------------|
| GET | `/api/v1/system/info` | Session | Info sistem, statistik database, dan status background task (`background`: `owner_pid`, `last_status_check`, `last_backup`, `last_cleanup`, `stale`) |
| GET | `/api/v1/notifications/config` | Session | Konfigurasi notifikasi |
| POST | `/api/v1/notifications/test` | Session | Kirim notifikasi test |
| GET | `/health` | Public | Health check |
| GET | `/ready` | Public | Readiness check |

### Web Routes

| Method | Endpoint | Auth | Keterangan |
|--------|----------|------|------------|
| GET | `/login` | Public | Halaman login |
| POST | `/login` | Public | Proses login |
| POST | `/logout` | Session + CSRF | Logout dan clear session |
| GET | `/logout` | Public | Hanya redirect ke `/login` (kompatibilitas), **tidak** mengakhiri sesi |
| GET | `/` | Session | Dashboard desktop |
| GET | `/d/<slug>` | Session | Dashboard by slug |
| GET | `/mobile` | Session | Dashboard mobile |
| GET | `/device/<id>` | Session | Detail device |
| GET | `/alerts` | Session | Redirect ke `/#alerts` |

---

## Struktur Proyek

```
AAthena/
├── app/                          # Package aplikasi FastAPI
│   ├── __init__.py               # Shim versi (dari app/main.py)
│   ├── main.py                   # App factory FastAPI: CORS, CSP/HSTS, Session, CSRF, error handlers, /health
│   ├── deps.py                   # Dependensi FastAPI: auth/session, workspace scope, throttle
│   ├── routers/                  # Route FastAPI per domain: ingest, devices, alerts, dashboards, users, system, chat, views
│   ├── alerts.py                 # Alert state machine
│   ├── api_common.py             # Helper bersama API (timestamp, device auth, purge)
│   ├── background.py             # Background worker + file lock
│   ├── config.py                 # Konfigurasi + validasi env (helper _env_*)
│   ├── database.py               # Layer SQLite koneksi + init runner
│   ├── migrations.py             # Migrasi v1..v19 + registry MIGRATIONS
│   ├── logging_config.py         # Setup log rotating
│   ├── notifier.py               # Dispatcher Telegram
│   ├── permissions.py            # Peran dan izin
│   ├── restore.py                # Restore database tertunda
│   ├── schemas.py                # Schema Pydantic
│   ├── utils.py                  # Helper: hash, lock, validator
│   └── workspace.py              # Scope multi-dashboard
├── .github/
│   └── workflows/
│       └── ci.yml                # Lint + pytest di GitHub Actions
├── esp32/
│   ├── main.py                   # Firmware MicroPython
│   └── secrets.example.py        # Template kredensial (salin ke secrets.py)
├── nginx/
│   ├── nginx.conf                # Konfigurasi utama Nginx
│   └── conf.d/
│       └── aaguard.conf            # Konfigurasi site
├── static/
│   ├── css/
│   │   ├── app.css               # Layout desktop
│   │   ├── chat.css              # Chat panel
│   │   ├── device-detail.css     # Halaman detail device
│   │   ├── fixes.css             # Override dan perbaikan
│   │   ├── mobile.css            # Layout mobile
│   │   ├── shared.css            # Design tokens dan reset
│   │   └── unified.css           # Sizing unifikasi
│   └── js/
│       ├── alert_rules_builder.js
│       ├── alerts.js
│       ├── api.js
│       ├── chat.js
│       ├── dashboard.js
│       ├── dashboard_store.js
│       ├── device-detail.js
│       ├── error-handler.js
│       ├── mobile.js
│       ├── sidebar.js
│       ├── theme.js
│       └── toast.js
├── tests/                        # Tes pytest (unit/integration + e2e Playwright)
├── templates/
│   ├── alerts.html               # Redirect ke /#alerts
│   ├── base.html                 # Base template
│   ├── dashboard.html            # Layout desktop
│   ├── device_detail.html        # Detail device
│   ├── login.html                # Halaman login
│   ├── mobile.html               # Layout mobile
│   └── partials/
│       ├── alerts_section.html
│       ├── chat_panel.html
│       ├── dashboard_section.html
│       ├── devices_section.html
│       ├── graph_section.html
│       ├── map_section.html
│       └── modals.html
├── .dockerignore
├── .env.example
├── .gitignore
├── docker-compose.yml
├── docker-compose.override.yml   # Hanya development (mount kode)
├── docker-entrypoint.sh
├── Dockerfile
├── LICENSE
├── Makefile
├── CHANGELOG.md
├── README.md
├── requirements.txt          # Dependensi produksi
├── requirements-dev.txt      # + pytest, ruff (dev dan CI)
├── ruff.toml                 # Aturan lint
├── run.py                        # Entry point
└── run.sh                        # Script start
```

---

## Sistem Alert

### State Machine

Setiap sensor dievaluasi terhadap tiga rentang: `healthy`, `warning`, dan `danger`. Alert memiliki lifecycle:

```
         +-----------+
         |  healthy  |
         +-----+-----+
               |
               | nilai keluar dari rentang healthy
               v
         +-----+-----+
         |  warning  |  <-- alert dibuat, notifikasi dikirim
         +-----+-----+
               |
               | nilai keluar dari rentang warning
               v
         +-----+-----+
         |  danger   |  <-- severity naik, notifikasi dikirim
         +-----+-----+
               |
               | nilai kembali ke rentang warning
               v
         +-----+-----+
         |  warning  |  <-- severity turun, alert diupdate
         +-----+-----+
               |
               | nilai kembali ke rentang healthy
               v
         +-----+-----+
         |  healthy  |  <-- alert ditutup, log cleared
         +-----------+
```

### Hysteresis

Untuk mencegah flip-flop di sekitar batas, sistem menerapkan hysteresis: nilai harus melewati batas sebesar `_hysteresis` sebelum severity berubah. Contoh untuk suhu dengan `_hysteresis: 0.5`: jika sedang danger dan suhu turun ke `32.0` sedangkan batas warning atas adalah `32`, perubahan ke warning tidak langsung terjadi sampai nilai berada di bawah `31.5`.

### Acknowledgment

Ketika pengguna menekan tombol Acknowledge, alert di-set `is_active = 0` dan dicatat di history. Namun, jika kondisi masih berlanjut, alert tidak akan langsung ter-trigger lagi. Sistem akan memeriksa:

- Jika severity baru sama atau lebih ringan dari severity saat di-ack, alert di-skip.
- Jika severity baru lebih berat dari severity saat di-ack (misalnya dari warning ke danger), alert ter-trigger lagi.

Setelah kondisi pulih sepenuhnya ke healthy, log `cleared` dicatat dan siklus siap dimulai ulang.

### Offline Detection

Device dianggap offline jika tidak mengirim data melebihi timeout efektif. Timeout efektif dihitung dengan prioritas:

1. `offline_timeout` manual yang di-set user.
2. `expected_interval * 2` jika interval terdeteksi otomatis.
3. Fallback `OFFLINE_TIMEOUT` dari env (default 900 detik).

### Auto-detect Interval

Setiap kali data masuk, sistem menghitung median delta waktu dari 5 data terakhir. Nilai median digunakan sebagai `expected_interval` baru jika berbeda dari yang lama. Nilai dibatasi antara 10 detik hingga 86400 detik (24 jam).

### Threshold Custom

Threshold bisa di-override per device melalui UI di modal Konfigurasi Monitoring. Format internal:

```json
{
  "temperature": {
    "healthy": {"min": 20, "max": 26},
    "warning": {"min": 15, "max": 30},
    "danger":  {"min": 10, "max": 35}
  }
}
```

Jika custom rule tidak diisi untuk sensor tertentu, sensor tersebut akan memakai global default.

---

## Multi-User dan Dashboard

Setiap pengguna memiliki set dashboard sendiri. Saat login pertama, dashboard default akan dibuat otomatis dengan slug `u<id>-default`.

### Hierarki

```
User
 └── Dashboard (banyak)
      ├── Analytics Tab (banyak)
      │    └── Widget (banyak)
      └── Widget tanpa tab
```

### Composite Unique

Tabel `dashboards` menggunakan composite unique constraint `(user_id, slug)`. Ini memungkinkan beberapa pengguna memiliki slug yang sama tanpa konflik.

### Widget Layout

Posisi dan ukuran widget disimpan di kolom `grid_x`, `grid_y`, `grid_w`, `grid_h`. Frontend menyimpan layout tambahan (lebar dan tinggi aktual dalam pixel) di `localStorage` dengan kunci `aaguard-chart-layout-<tab_id>`.

### Migrasi Data Legacy

Ketika pengguna login dan dashboard dengan `user_id IS NULL` masih ada, dashboard tersebut akan di-assign ke pengguna tersebut. Ini memastikan instalasi yang lama tetap berjalan setelah upgrade ke multi-user.

---

## AAguard AI Chat

Chat panel terintegrasi yang memanggil LLM melalui API OpenAI-compatible. Mendukung function calling: LLM dapat memanggil tool untuk query database, lalu merangkum hasilnya dalam bahasa natural.

### Tool yang Tersedia

| Tool | Deskripsi | Parameter |
|------|-----------|-----------|
| `get_devices_status` | Status semua device | - |
| `get_active_alerts` | Alert yang sedang aktif | - |
| `get_device_history` | Riwayat sensor device | `device_id`, `hours` |

### Alur

1. Frontend mengirim `messages` ke `POST /api/v1/chat`.
2. Server memanggil LLM dengan daftar tool.
3. Jika LLM meminta tool, server menjalankan tool tersebut dan mengirim hasilnya kembali.
4. LLM merangkum hasil dalam bahasa natural.
5. Server mengembalikan `reply` dan `tools_used` ke frontend.

### Konfigurasi

Contoh untuk OpenRouter:

```env
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_API_KEY=sk-or-v1-xxxxxxxxxxxx
LLM_MODEL=meta-llama/llama-3.3-70b-instruct:free
LLM_TIMEOUT=120
```

Contoh untuk Ollama lokal:

```env
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=ollama
LLM_MODEL=llama3.1:8b
LLM_TIMEOUT=120
```

Contoh untuk vLLM:

```env
LLM_BASE_URL=http://localhost:8000/v1
LLM_API_KEY=sk-no-key
LLM_MODEL=Qwen/Qwen2.5-7B-Instruct
LLM_TIMEOUT=120
```

Jika `LLM_API_KEY` kosong, fitur chat dianggap belum dikonfigurasi: tombol/panel chat tidak dirender, tidak ada polling `/api/v1/chat/health`, dan `POST /api/v1/chat` menjawab 503. Jika `LLM_BASE_URL` tidak dapat dijangkau, panel chat menampilkan status offline namun aplikasi tetap berjalan normal.

### Batas dan Keamanan Chat

- Dari klien hanya pesan `role` `user`/`assistant` dengan `content` berupa string yang diteruskan; field lain dibuang. Maksimum 10 pesan terakhir, tiap pesan dipotong ke 4000 karakter.
- Hasil tool dibatasi maksimum 100 baris per daftar dan 20 KB JSON; bila dipotong, hasil memuat `truncated: true`.
- LLM boleh memanggil tool hingga 3 putaran (maksimum 5 panggilan per putaran), lalu wajib memberi jawaban teks.
- System prompt menegaskan bahwa isi data (nama device, pesan alert) adalah data, bukan instruksi.
- Detail error internal hanya dicatat di log; klien menerima pesan generik.
- Semua user yang login dapat memakai chat.

---

## Background Tasks

Tiga background task dijalankan oleh worker yang memegang lock file. Hanya satu worker dari N worker Gunicorn yang menjalankan task.

### Status Checker

Interval: `CHECK_INTERVAL` detik (default 60).

- Memeriksa setiap device apakah melewati timeout offline.
- Set status `offline` jika melewati timeout.
- Set status `online` jika menerima data kembali.
- Trigger alert offline sesuai severity yang dikonfigurasi.

### Data Cleanup

Interval: 24 jam. Delay inisial: 5 menit.

Menghapus data berdasarkan retensi:

| Tabel | Retensi |
|-------|---------|
| `sensor_data` | `DATA_RETENTION_DAYS` |
| `alert_history` | `ALERT_HISTORY_RETENTION_DAYS` |
| `device_status_log` | `STATUS_LOG_RETENTION_DAYS` |
| `alerts` (yang tidak aktif) | `ALERT_HISTORY_RETENTION_DAYS` |

Jika total baris yang dihapus melebihi 1000, `VACUUM` dijalankan untuk mengembalikan ruang ke OS.

### Backup

Interval: `BACKUP_INTERVAL_HOURS` jam. Jeda boot: 30 detik, lalu backup langsung bila belum ada backup yang cukup baru (lebih muda dari interval, maksimal 24 jam); tidak menunggu tanpa syarat.

- Backup database dengan SQLite Online Backup API.
- Simpan ke `BACKUP_DIR/iot_<timestamp>.db` (timestamp WIB).
- Hapus **hanya** file `iot_*.db` yang lebih tua dari `BACKUP_RETENTION_DAYS`, dan selalu sisakan minimal `BACKUP_MIN_KEEP` backup terbaru.
- `pre-restore-*.db` dan file lain di folder backup **tidak pernah dihapus otomatis**; bersihkan manual bila perlu.

### Restore Database

`POST /api/v1/system/restore` (admin) **tidak menimpa database yang sedang berjalan**. Endpoint memverifikasi file backup, membuat `pre-restore-*.db`, lalu menyiapkan `<DB_PATH>.restore-pending` dan penanda `<DB_PATH>.restore-marker`. Restore diterapkan saat proses **start berikutnya**, sebelum koneksi database dibuka: `-wal`/`-shm` dihapus, database diganti, penanda dibuang. Hentikan semua worker lalu start ulang (`docker compose restart aaguard-iot`). Jika database masih dipakai proses lain, penerapan ditunda sampai start berikutnya dan dicatat di log.

### Status dan Heartbeat

Setiap task mencatat heartbeat (tabel `user_settings`, kunci `bg_hb_*`) yang ditampilkan di `/api/v1/system/info` → `background`. Sebuah task ditandai `stale` bila heartbeat terakhirnya lebih tua dari 3× intervalnya.

### Lock File

Lock file disimpan di `AAGUARD_LOCK_DIR` (default `/tmp`). Nama file: `aaguard-background.lock`. Untuk deployment multi-container, direktori ini harus di-share antar-container, atau cukup satu container yang menjalankan background task.

Worker yang tidak mendapat lock **tidak berhenti**: ia mencoba lagi tiap 30 detik, sehingga bila pemegang lock mati atau di-recycle (`--max-requests`), worker lain mengambil alih.

---

## Database dan Migrations

Database: SQLite dengan mode WAL. Schema saat ini versi 19.

### Tabel

| Tabel | Deskripsi |
|-------|-----------|
| `schema_version` | Versi schema yang diterapkan |
| `users` | Akun pengguna |
| `devices` | Device terdaftar |
| `sensor_data` | Data sensor time series |
| `alerts` | Alert aktif |
| `alert_history` | Riwayat perubahan alert |
| `device_status_log` | Log perubahan status device |
| `dashboards` | Dashboard per pengguna |
| `analytics_tabs` | Tab analitik per dashboard |
| `widgets` | Widget chart per tab |
| `user_settings` | Key-value settings per user (juga menyimpan global alert rules dan heartbeat background task) |
| `login_failures` | Penghitung login gagal untuk throttle (per username+IP dan per IP) |

### Migration

Migrasi dijalankan otomatis saat aplikasi start. Setiap migrasi diberi versi dan diterapkan hanya jika versi saat ini lebih kecil. Untuk deployment multi-worker, migrasi dilindungi oleh file lock `db-init` sehingga hanya satu worker yang menjalankannya.

Daftar migrasi:

| Versi | Perubahan |
|-------|-----------|
| 1 | Tabel inti: devices, sensor_data, alerts |
| 2 | Kolom `last_ip` dan `firmware_version` |
| 5 | Kolom offline timeout, expected interval, alert rules; tabel `alert_history`, `device_status_log`, `user_settings` |
| 6 | Index tambahan untuk performa query alert |
| 7 | Standardisasi timezone ke naive WIB |
| 8 | Hashing API key dengan SHA-256 |
| 9 | Tabel `dashboards` dan `widgets` |
| 10 | Tabel `analytics_tabs`, kolom `analytics_tab_id` pada widgets |
| 11 | Perbaikan constraint NOT NULL pada `api_key` |
| 12 | Multi-user: tabel `users`, kolom `user_id` pada dashboards |
| 13 | Perbaikan referensi FK yang stale |
| 14 | Verifikasi dan perbaikan integritas FK |
| 15 | Kolom `devices.interval_manual` (interval manual tidak ditimpa auto-detect) |
| 16 | Tabel `login_failures` untuk throttle login |

### Retention

Data dihapus oleh background task cleanup. Frekuensi penghapusan 24 jam. Timezone yang digunakan adalah WIB (UTC+7) dengan naive datetime.

---

## Deployment Produksi

### Docker Compose

Setup minimal:

```bash
git clone https://github.com/takathena/AAthena.git
cd AAthena

cp .env.example .env
nano .env
```

Isi `SECRET_KEY` dan `IOT_PASSWORD`. Jika di belakang HTTPS, set `SESSION_COOKIE_SECURE=True` dan `ENABLE_HSTS=True`.

```bash
mkdir -p database logs backup
chown -R 1000:1000 database logs backup

docker compose up -d --build
docker compose ps
```

Akses publik di port `NGINX_PORT` (default 4455) dan `443` (HTTPS). Port internal FastAPI/uvicorn (5000) tidak ter-expose ke host, hanya ke network internal Docker.

**Kode ada di dalam image.** `docker-compose.yml` tidak lagi me-mount `./app`, `./templates`, `./static` ke container FastAPI (Nginx tetap menyajikan `./static`). Rilis v2.0.0 diterbitkan sebagai image `aaguard-iot:2.0.0` (tag Docker dari `aaguard-iot:latest`, sesuai git tag `v2.0.0`). Perubahan kode butuh build ulang:

```bash
git pull
docker compose -f docker-compose.yml up -d --build      # atau: make docker-up
```

Untuk **development** (mount kode, tanpa build ulang), gunakan `docker-compose.override.yml`, yang dimuat otomatis oleh `docker compose up` biasa (atau `make docker-dev-up`). Jangan menjalankan `docker compose up` tanpa `-f docker-compose.yml` di server produksi.

Gunicorn berjalan dengan `--timeout 60 --graceful-timeout 30 --max-requests 1000 --max-requests-jitter 100` (worker di-recycle berkala). Jumlah worker dari `WEB_CONCURRENCY`. Nginx memakai `proxy_read_timeout 180s` khusus `/api/v1/chat`; jika `LLM_TIMEOUT` dinaikkan, naikkan nilai itu (≥ 1,5×).

### Systemd

Tanpa Docker:

```bash
sudo useradd -r -s /bin/false aaguard
sudo mkdir -p /opt/aaguard-iot
sudo chown aaguard:aaguard /opt/aaguard-iot

cd /opt/aaguard-iot
sudo -u aaguard git clone https://github.com/takathena/AAthena.git .
sudo -u aaguard python3 -m venv venv
sudo -u aaguard venv/bin/pip install -r requirements.txt
sudo -u aaguard cp .env.example .env
sudo nano .env
```

Buat service file `/etc/systemd/system/aaguard-iot.service`:

```ini
[Unit]
Description=AAguard IoT Platform
After=network.target

[Service]
Type=simple
User=aaguard
Group=aaguard
WorkingDirectory=/opt/aaguard-iot
Environment="PATH=/opt/aaguard-iot/venv/bin"
ExecStart=/opt/aaguard-iot/venv/bin/gunicorn -w 4 -k uvicorn.workers.UvicornWorker -b 127.0.0.1:5000 run:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Aktifkan:

```bash
sudo systemctl daemon-reload
sudo systemctl enable aaguard-iot
sudo systemctl start aaguard-iot
sudo systemctl status aaguard-iot
```

### Nginx Reverse Proxy

Contoh konfigurasi:

```nginx
server {
    listen 80;
    server_name iot.example.com;

    location /static/ {
        alias /opt/aaguard-iot/static/;
        expires 30d;
        add_header Cache-Control "public, immutable";
        access_log off;
    }

    location = /health {
        proxy_pass http://127.0.0.1:5000/health;
        access_log off;
    }

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;

        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

Catatan: aplikasi membaca `X-Forwarded-For` di belakang reverse proxy (lihat `app/deps.py:client_ip`) sehingga IP asli klien tetap tercatat.

### HTTPS

Direkomendasikan menggunakan Certbot dengan Nginx:

```bash
sudo certbot --nginx -d iot.example.com
```

Setelah HTTPS aktif, update `.env`:

```env
SESSION_COOKIE_SECURE=True
ENABLE_HSTS=True
```

Restart aplikasi.

### Multi-Worker Considerations

Rate limiting menggunakan storage `memory://` sehingga tidak shared antar-worker Gunicorn. Untuk deployment dengan banyak worker dan traffic tinggi, ganti ke Redis:

```bash
pip install redis
```

```env
RATE_LIMIT_STORAGE=redis://localhost:6379/0
```

Background task sudah aman untuk multi-worker karena dilindungi file lock. Hanya satu worker yang menjalankan task; worker lain mengambil alih otomatis bila pemiliknya mati (retry tiap 30 detik).

---

## Makefile Reference

### Development

| Target | Fungsi |
|--------|--------|
| `make help` | Tampilkan daftar target |
| `make dev` | Setup virtualenv, install dependency (termasuk dev), buat `.env` |
| `make install` | Install dependency produksi saja |
| `make install-dev` | Install dependency produksi + dev (pytest, ruff) |
| `make run` | Jalankan dev server |
| `make run-prod` | Jalankan Gunicorn di foreground |
| `make backup` | Backup database manual |
| `make test` | Jalankan `pytest -q` |
| `make lint` | `ruff check app run.py` (undefined name, import tak terpakai) |
| `make health` | Cek endpoint `/health` pada server yang sedang jalan |
| `make clean` | Hapus venv, cache, dan file sementara |

### Docker

| Target | Fungsi |
|--------|--------|
| `make docker-build` | Build image |
| `make docker-up` | Start container produksi di background (tanpa override dev) |
| `make docker-dev-up` | Start container development (mount kode via `docker-compose.override.yml`) |
| `make docker-down` | Stop container |
| `make docker-restart` | Restart container |
| `make docker-rebuild` | Rebuild dari nol dan restart |
| `make docker-logs` | Stream log |
| `make docker-shell` | Masuk ke shell container |

---

## Keamanan

### CSRF Protection

Semua endpoint POST, PUT, PATCH, dan DELETE membutuhkan CSRF token via header `X-CSRFToken` atau field form `csrf_token`. Token di-generate per-session dan tidak expire otomatis selama session aktif.

Satu-satunya endpoint yang di-exempt adalah `POST /api/v1/data` karena device tidak memiliki session browser.

### API Key

API key device di-hash dengan SHA-256 sebelum disimpan. Verifikasi menggunakan `hmac.compare_digest` untuk mencegah timing attack. API key plain-text hanya ditampilkan sekali saat device dibuat atau di-regenerate.

### Session

- Cookie `HttpOnly` untuk mencegah akses via JavaScript.
- Cookie `SameSite=Lax` untuk mencegah CSRF via navigasi lintas situs.
- Cookie `Secure` harus diaktifkan jika di belakang HTTPS.
- Idle timeout terpisah dari lifetime session. Endpoint polling API tidak memperpanjang idle, sehingga tab yang dibiarkan terbuka tidak akan membuat session aktif terus.

### Rate Limiting

Endpoint `POST /api/v1/data` dibatasi 60 request per menit **per `device_id`** (plafon 600 per menit per IP). Endpoint login dibatasi 5 percobaan per menit per IP, ditambah penguncian kegagalan per username+IP (`LOGIN_MAX_FAILURES`) dan per IP (`LOGIN_IP_MAX_FAILURES`); penyerang dari IP lain tidak bisa mengunci admin yang sah. Endpoint regenerate API key dibatasi 10 per menit. Endpoint API umum dibatasi 200 per menit.

### Security Headers

Aplikasi mengirim header berikut pada setiap response:

- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: SAMEORIGIN`
- `X-XSS-Protection: 1; mode=block`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy: geolocation=(), microphone=(), camera=(), payment=(), usb=()`
- `Content-Security-Policy` dengan default-src self

`Strict-Transport-Security` dikirim hanya jika `ENABLE_HSTS=True` (tidak lagi bergantung pada `SESSION_COOKIE_SECURE`).

### Input Validation

- Payload device divalidasi dengan Pydantic schema (`app/schemas.py`): panjang string, regex untuk Device ID, range untuk integer.
- Alert rules divalidasi sebelum disimpan: struktur object, min lebih kecil dari max, nilai numerik.
- SQL injection dicegah dengan parameterized query di semua layer database.
- XSS dicegah dengan escaping di template Jinja2 dan di JavaScript (fungsi `escapeHtml`).

### Config Validation

Saat start, `config.validate()` memeriksa:

- `SECRET_KEY` ada dan tidak diawali `CHANGE_ME`.
- `IOT_PASSWORD` ada dan bukan default.
- Port dalam range valid.
- Timeout dan interval minimal 10 detik.
- Jika notifikasi aktif, token dan chat ID Telegram harus diisi.

Jika ada error, aplikasi gagal start dengan pesan yang jelas.

---

## Troubleshooting

### Login gagal dengan error CSRF

Gejala: form login mengembalikan "Sesi tidak valid".

Penyebab: token CSRF expired atau cookie tidak tersimpan.

Solusi: hard refresh browser (`Ctrl+Shift+R`). Jika masih gagal, clear cookie untuk domain tersebut.

### Session hilang setiap restart

Gejala: harus login ulang setiap container restart.

Penyebab: `SECRET_KEY` di-generate acak saat start.

Solusi: set `SECRET_KEY` permanen di `.env` dengan `secrets.token_hex(32)`.

### Permission denied di Docker

Gejala: container exit dengan error tulis ke `database` atau `logs`.

Penyebab: host directory di-mount sebagai root, container berjalan sebagai user aaguard (UID 1000).

Solusi:

```bash
docker compose down
sudo chown -R 1000:1000 database logs backup
docker compose up -d
```

### Container unhealthy

Gejala: `docker compose ps` menampilkan status unhealthy.

Solusi:

```bash
docker compose logs aaguard-iot | tail -50
curl -v http://localhost:4455/health
```

Jika `/health` mengembalikan 503, cek file log untuk detail error.

### Database locked

Gejala: error `sqlite3.OperationalError: database is locked`.

Penyebab: journal mode bukan WAL, atau ada proses lain yang memegang lock eksklusif.

Solusi:

```bash
sqlite3 database/iot.db "PRAGMA journal_mode;"
# Harus mengembalikan: wal
```

Jika bukan `wal`:

```bash
sqlite3 database/iot.db "PRAGMA journal_mode=WAL;"
```

### Data tidak masuk dari device

Gejala: device mengirim data tapi tidak muncul di dashboard.

Penyebab umum:

1. API key salah. Cek log server untuk pesan `Invalid API key attempt`.
2. Device ID tidak sesuai dengan yang terdaftar.
3. Rate limit terlampaui. Cek log untuk `429 Too Many Requests`.
4. Payload bukan JSON valid. Cek log untuk `Invalid JSON`.

Solusi: cek log dengan `docker compose logs -f aaguard-iot` atau `tail -f logs/aaguard.log.*` (satu file per worker).

### Alert tidak muncul

Penyebab umum:

1. Sensor key di payload tidak match dengan alert rules. Cek `sensor_data.data` untuk memastikan nama key.
2. Nilai sensor masih dalam rentang healthy.
3. Alert di-skip karena sudah di-ack dan severity tidak memburuk.
4. Custom alert rules device menimpa global dengan rentang yang lebih longgar.

Solusi: cek tab Alert Center, dan cek log alert di `alert_history`.

### Chart tidak render

Penyebab umum:

1. Belum ada tab analitik. Buat tab dulu.
2. Tab tidak punya widget. Klik Tambah Diagram.
3. Widget ada tapi device atau sensor key salah. Edit widget.
4. Chart.js gagal load dari CDN. Cek console browser.

### Chat AI offline

Gejala: status di header chat panel menampilkan "Offline".

Penyebab: `LLM_BASE_URL` tidak dapat dijangkau.

Solusi:

```bash
curl -v $LLM_BASE_URL/models \
  -H "Authorization: Bearer $LLM_API_KEY"
```

Pastikan endpoint upstream berjalan dan API key valid.

### Rate limit false positive di belakang Nginx

Gejala: user dari IP berbeda dianggap IP yang sama.

Penyebab: Nginx tidak mengirim header `X-Forwarded-For`.

Solusi: pastikan Nginx mengirim header `X-Real-IP` dan `X-Forwarded-For`; aplikasi membaca IP dari header tersebut (`app/deps.py:client_ip`).

### Memory usage terus naik

Penyebab umum:

1. Jumlah data besar dan belum di-cleanup. Cek konfigurasi retensi.
2. Rate limit `memory://` menampung banyak IP. Ganti ke Redis.
3. Background task menumpuk. Cek log untuk error berulang.

Solusi:

```bash
# Cek ukuran database
ls -lh database/

# Cek jumlah baris
sqlite3 database/iot.db "SELECT COUNT(*) FROM sensor_data;"

# Trigger manual cleanup dengan restart container
docker compose restart aaguard-iot
```

---

## Kebijakan dan Perilaku Penting

Ringkasan perilaku yang sengaja diubah pada perbaikan V6.5 dan perlu diketahui operator.

### Kebijakan peran admin (C2)

Semua route yang **mengubah** data adalah admin-only dan dijaga di backend (JSON `403` untuk non-admin):
tambah/ubah/hapus device, regenerate API key, ubah/reset alert rules per device, Bulk Import,
tes notifikasi, serta manajemen user/backup/restore/cleanup/global rules.
Request `GET` (baca) tetap terbuka untuk semua user yang login. Tombol terkait disembunyikan di UI untuk non-admin,
tetapi backend adalah sumber kebenaran.

### Password admin (H3)

`IOT_USERNAME` / `IOT_PASSWORD` di `.env` hanya dipakai **sekali** untuk membuat admin pertama (saat tabel `users` masih kosong; instalasi lama sudah punya admin dari migrasi v12).
Setelah itu login hanya memakai hash di database. Untuk mengganti password admin gunakan UI (**Ganti Password**); mengubah `IOT_PASSWORD` di `.env` tidak berpengaruh pada admin yang sudah ada.

### Cookie sesi dan HTTPS (H7)

`SESSION_COOKIE_SECURE` tidak lagi dipaksa `True` di production. Jika env tidak di-set, nilainya mengikuti `ENABLE_HSTS`.
Header HSTS hanya dikirim bila `ENABLE_HSTS=True`. Jika production berjalan dengan `SESSION_COOKIE_SECURE=False`,
log start memuat peringatan (gunakan hanya di jaringan tepercaya tanpa HTTPS).

### Alert rules: global + override per device (C3/C4)

- **Global rules** (menu *Global Rules*, tersimpan di DB) menimpa default `config.ALERT_RULES` **per sensor** dan dibaca langsung oleh mesin alert.
  Hasilnya di-cache ±45 detik; perubahan langsung berlaku di worker yang menerima request, worker lain menyusul paling lama sekitar 45 detik.
  *Reset* global rules mengembalikan ke default config. Jika data tersimpan korup, default dipakai (peringatan dicatat di log).
- **Rules per device** menimpa global **hanya untuk sensor yang didefinisikan**; sensor lain mengikuti global.

### Interval device: manual vs otomatis (N2)

- Mengisi **Expected Interval** (saat tambah/edit device) menandai interval sebagai **manual**; auto-detect tidak akan menimpanya.
- Mengosongkan field di form edit mengembalikan device ke mode **otomatis**.
- Auto-detect hanya untuk device non-manual: butuh minimal 5 data terakhir, selisih < 2 detik diabaikan, hasil tidak di bawah 10 detik, dan hanya menulis bila berubah > 20%.
- Menyimpan form edit dengan nilai yang sama dengan hasil auto-detect tidak mengubah mode.

### Payload `/api/v1/data` (M1)

- Body maksimal `DATA_MAX_BYTES` (default 8192 byte), lebih dari itu HTTP 413.
- `data` harus object datar, maks 32 key (`[a-zA-Z0-9_]{1,32}`); nilai berupa angka finite, boolean, atau string maks 64 karakter. `sensor_type` memakai `[A-Za-z0-9_-]{1,32}`.
- Ekspor CSV menetralkan sel berawalan `= + - @` (diberi awalan `'`).

---

## Pengembangan dan Tes

### Menjalankan tes dan lint

```bash
make dev            # virtualenv + dependensi produksi dan dev (requirements-dev.txt)
make test           # python -m pytest -q
make lint           # ruff check app run.py
```

Tanpa Makefile:

```bash
pip install -r requirements-dev.txt
python -m pytest -q
ruff check app run.py
```

Tes memakai database sementara dan konfigurasi `testing`; tidak menyentuh `database/iot.db`. Nama berkas tes (`test_phaseN_*.py`) mengikuti urutan fase perbaikan; setiap temuan di [CHANGELOG](CHANGELOG.md) punya minimal satu tes.

### Tes E2E browser (Playwright)

Tes E2E menjalankan browser sungguhan terhadap instance yang sudah berjalan dan **mengubah database live** (membuat lalu menghapus satu device uji). Karena itu tes ini opt-in:

```bash
pip install playwright
playwright install chromium

E2E=1 pytest -q tests/e2e/test_live_e2e.py
```

Kredensial diambil dari `E2E_USERNAME`/`E2E_PASSWORD`, atau fallback ke `IOT_USERNAME`/`IOT_PASSWORD` di `.env`. Target default `http://localhost:4455`; ubah dengan `E2E_BASE_URL`. Skenario: login, metrik dashboard, navigasi semua section, marker peta, command palette, tab pengaturan, logout, dan create/delete device.

### CI

`.github/workflows/ci.yml` menjalankan lint dan tes pada setiap push ke `main` dan setiap pull request (Python 3.11, dependensi dari `requirements-dev.txt`).
Dependensi dev tidak dipasang di image Docker (`Dockerfile` hanya memasang `requirements.txt`; `requirements-dev.txt`, `tests/`, dan `.github/` dikecualikan lewat `.dockerignore`).

### Versi

Versi aplikasi didefinisikan satu kali di `app/main.py` (`__version__`) dan dipakai oleh `/health`, `/system/info` (kartu **Versi Aplikasi** di UI), serta dicek oleh tes terhadap badge README dan judul CHANGELOG.
Saat menaikkan versi: ubah `__version__`, badge di README, dan tambahkan judul `## V<versi>` di CHANGELOG, lalu jalankan `make test`.

---

## Lisensi

MIT License. Lihat file [LICENSE](LICENSE) untuk teks lengkap.

Copyright (c) 2026 AAguard IoT Platform
