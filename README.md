# iot-go — Rebuild ramping Nexus IoT

> Branch `rebuild/go-mvp`. Versi lama (Python/Flask) tetap ada di branch `main`.
> Tujuan: rebuild Nexus IoT dengan stack, fitur, dan dokumentasi yang lebih terstruktur.

## Fitur MVP

- **Sensor:** DHT22 (suhu + kelembaban), asap (SMOKE), dan sensor generik via API — `sensor_type` bebas, `data` disimpan sebagai JSON.
- **Device & ingest:** tambah device → API key tampil **sekali saja** (di server hanya disimpan hash SHA-256) → device `POST /data` → key diverifikasi (constant-time) → simpan.
- **Dashboard:** 1 halaman di `GET /`, tema dark/light (toggle + ikut `prefers-color-scheme`, tersimpan di browser), refresh 30 detik, tanpa framework JS.
- **Deploy:** Docker Compose (1 service, volume `./data`).

## Stack

Go 1.24 (stdlib `net/http` + `html/template`) + SQLite (`modernc.org/sqlite`, pure-Go tanpa cgo). Tanpa framework web, tanpa ORM.

## Struktur

```
main.go              entry + config env (PORT, DB_PATH, ADMIN_TOKEN)
internal/api/        semua HTTP + template dashboard, tanpa SQL
internal/store/      semua SQLite + hash API key
Dockerfile           multi-stage build → Alpine
docker-compose.yml   1 service
```

## API

| Method | Path | Keterangan |
|---|---|---|
| `POST /devices` | Header `X-Admin-Token` (bila `ADMIN_TOKEN` diset) | Buat device → balas `api_key` sekali saja |
| `GET /devices` | | List device |
| `POST /data` | Body: `device_id, api_key, sensor_type, data` | Ingest data sensor |
| `GET /devices/{id}/history?limit=100` | | Riwayat data (maks 1000) |
| `GET /` | | Dashboard (dark/light) |
| `GET /health` | | Health check |

Contoh payload:

```json
{"device_id":"ESP32-001","api_key":"...","sensor_type":"DHT22","data":{"temperature":25.5,"humidity":60}}
{"device_id":"ESP32-002","api_key":"...","sensor_type":"SMOKE","data":{"ppm":120}}
```

## Jalan

Lokal:

```bash
go mod tidy
ADMIN_TOKEN=rahasia PORT=8080 go run .
```

Docker (VPS):

```bash
cp .env.example .env   # isi ADMIN_TOKEN yang kuat
mkdir -p data && chown 10001:10001 data   # volume harus bisa ditulis user container
docker compose up -d --build
# Di Debian tanpa plugin compose, perintahnya: docker-compose up -d --build
curl http://<IP-VPS>:8080/health
```

ESP32: arahkan `API_URL` ke `http://<IP-VPS>:8080/data`.

## Roadmap

- **Fase 2 — Alert:** ambang batas per sensor (suhu/asap), status warning/danger, riwayat alert. Sengaja belum dibuat di MVP.

Dokumentasi lengkap Fase 1 (arsitektur, API, cara cek, troubleshooting): [docs/FASE1.md](docs/FASE1.md).
