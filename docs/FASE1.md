# Fase 1 — MVP iot-go (Selesai)

Rebuild ramping Nexus IoT. Fokus: ingest data sensor → simpan → tampil di dashboard.
Alert sengaja **Fase 2**.

## 1. Tujuan

Mengganti stack lama (Python/Flask, di branch `main`) dengan stack yang lebih
terstruktur: Go + SQLite + Docker Compose, fitur inti saja, dokumentasi lengkap.

## 2. Arsitektur

```
ESP32 ──POST /data──► iot-go (:8080) ──► SQLite (/data/iot.db)
                           │
                           └──► GET / dashboard (HTML, tema dark/light)
Browser ─────────────────► iot-go
```

- Semua HTTP lewat `net/http` (stdlib Go, tanpa framework).
- Semua SQL terisolasi di `internal/store`.
- Waktu disimpan UTC format RFC3339.

## 3. Struktur repo

```
main.go                  entry + config env
internal/api/api.go      handler HTTP + template dashboard (tanpa SQL)
internal/store/store.go  SQLite + hash API key
internal/store/store_test.go  self-check hash
Dockerfile               build Go 1.26 → Alpine, user non-root (10001)
docker-compose.yml       1 service, volume ./data
.env.example             contoh konfigurasi
docs/FASE1.md            dokumen ini
```

## 4. Sensor yang didukung

`sensor_type` bebas (string), `data` disimpan mentah sebagai JSON. Yang direncanakan:

| Sensor | sensor_type | Contoh data |
|---|---|---|
| DHT22 (suhu + kelembaban) | `DHT22` | `{"temperature":25.5,"humidity":60}` |
| Asap | `SMOKE` | `{"ppm":120}` |
| Generik (sensor apa pun via API) | bebas | `{"v":1}` |

## 5. Model data

```sql
devices(device_id TEXT PK, name TEXT, api_key_hash TEXT,
        last_seen TEXT, created_at TEXT)
sensor_data(id INTEGER PK, device_id TEXT, sensor_type TEXT,
            data TEXT, timestamp TEXT)
```

API key hanya disimpan sebagai hash SHA-256 hex. Plain-text hanya dikembalikan
satu kali saat device dibuat.

## 6. API

| Method | Path | Auth | Keterangan |
|---|---|---|---|
| `POST /devices` | header `X-Admin-Token` (bila `ADMIN_TOKEN` diset) | admin | Buat device → `201 {"device_id","api_key"}` |
| `GET /devices` | — | — | List device + `last_seen` |
| `POST /data` | body JSON | `api_key` device | Ingest → `200 {"status":"saved"}` |
| `GET /devices/{id}/history?limit=100` | — | — | Riwayat, terbaru dulu, `limit` maks 1000 |
| `GET /` | — | — | Dashboard HTML |
| `GET /health` | — | — | `{"status":"ok"}` |

Status error: `400` JSON tidak valid / field wajib kosong, `401` token/key salah,
`404` device tidak ditemukan, `413` body > 64 KB.

## 7. Dashboard

Satu halaman `GET /`: daftar device, data terakhir (sensor + nilai + waktu),
riwayat 10 terakhir per device. Tema **dark/light** via tombol, disimpan di
`localStorage`, default mengikuti `prefers-color-scheme`. Refresh otomatis
30 detik (`<meta refresh>`), tanpa framework JS/chart.

## 8. Keamanan

- API key: SHA-256 + perbandingan constant-time (`subtle.ConstantTimeCompare`).
- `POST /devices` dilindungi `ADMIN_TOKEN` bila diset; kosong = terbuka (dev saja).
- Body dibatasi 64 KB. Template `html/template` (auto-escape).
- Container jalan sebagai user non-root (UID 10001).

## 9. Konfigurasi (env)

| Variabel | Default | Keterangan |
|---|---|---|
| `PORT` | `8080` | Port listen |
| `DB_PATH` | `iot.db` | Path SQLite (Docker: `/data/iot.db`) |
| `ADMIN_TOKEN` | kosong | Token untuk `POST /devices` |

## 10. Menjalankan

Lokal (Go 1.26+):

```bash
go mod tidy
ADMIN_TOKEN=rahasia PORT=8080 go run .
```

Docker Compose (VPS):

```bash
cp .env.example .env        # isi ADMIN_TOKEN yang kuat
mkdir -p data && chown 10001:10001 data   # volume harus bisa ditulis user container
docker compose up -d --build
# Di Debian tanpa plugin compose, perintahnya: docker-compose up -d --build
```

ESP32: `API_URL = "http://<IP-VPS>:8080/data"`.

## 11. Cara cek Fase 1 (checklist verifikasi)

Jalankan urut, bandingkan hasilnya:

```bash
# 0. health
curl localhost:8080/health
# → {"status":"ok"}

# 1. buat device (catat api_key — hanya muncul sekali)
curl -X POST localhost:8080/devices -H 'X-Admin-Token: rahasia' \
  -d '{"device_id":"ESP32-001","name":"Ruang Server"}'
# → {"device_id":"ESP32-001","api_key":"<64 char hex>"}

# 2. kirim data DHT22
curl -X POST localhost:8080/data \
  -d '{"device_id":"ESP32-001","api_key":"<key>","sensor_type":"DHT22","data":{"temperature":25.5,"humidity":60}}'
# → {"status":"saved"}

# 3. kirim data asap
curl -X POST localhost:8080/data \
  -d '{"device_id":"ESP32-001","api_key":"<key>","sensor_type":"SMOKE","data":{"ppm":120}}'
# → {"status":"saved"}

# 4. key salah harus ditolak
curl -X POST localhost:8080/data \
  -d '{"device_id":"ESP32-001","api_key":"SALAH","sensor_type":"DHT22","data":{}}'
# → 401 {"error":"api_key salah"}

# 5. list + riwayat
curl localhost:8080/devices
curl localhost:8080/devices/ESP32-001/history
# → device muncul dengan last_seen; 2 baris data (SMOKE terbaru dulu)

# 6. dashboard di browser: http://<IP>:8080/
# → device + data terakhir (25.5°C / 120 ppm) tampil; tombol Tema mengganti dark/light
```

Hasil test di VPS tanggal 2026-11-07 (Docker Compose): semua langkah di atas
lolos, termasuk data DHT22 + SMOKE tersimpan dan muncul di dashboard.

## 12. Troubleshooting

| Gejala | Penyebab & solusi |
|---|---|
| Container `Restarting`, log `unable to open database file` | `data/` tidak bisa ditulis user 10001 → `chown 10001:10001 data` |
| `go.mod requires go >= 1.26.0` di Docker build | `Dockerfile` harus `golang:1.26-alpine` (sudah) |
| `docker: 'compose' is not a docker command` | Debian: pakai `docker-compose` (paket `docker-compose`) |
| Port 8080 tidak reachable dari luar | Buka TCP 8080 di firewall panel VPS |
| `401 admin token salah` | Header `X-Admin-Token` tidak cocok dengan `ADMIN_TOKEN` |

## 13. Batasan yang diketahui (sengaja, Fase 1)

- Tanpa login user — dashboard & list device terbuka untuk siapa pun yang tahu IP.
- Tanpa HTTPS — `api_key` berjalan polos bila diakses dari internet.
- Tanpa alert, tanpa retensi data otomatis, tanpa backup.
- Satu koneksi SQLite (`SetMaxOpenConns(1)`) — cukup untuk ingest ringan.

## 14. Roadmap Fase 2 — Alert

Ambang batas per sensor (suhu, asap), status warning/danger, riwayat alert,
notifikasi. Dibahas terpisah sebelum dibangun.
