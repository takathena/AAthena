# Fase 4 — Kalibrasi Sensor dari Dashboard

> Di atas Fase 3 ([FASE3.md](FASE3.md)): ambang alert yang tadinya konstanta kini bisa dikalibrasi dari dashboard, disimpan di DB, dan langsung dipakai ingest berikutnya.

## 1. Konsep Range

Dua batas per sensor membagi nilai menjadi tiga range:

| Range | DHT22 (`temperature`, °C) | SMOKE (`ppm`) |
|---|---|---|
| **Normal** (`ok`) | `< warning` | `< warning` |
| **Warning** | `warning ≤ suhu < danger` | `warning ≤ ppm < danger` |
| **Danger** | `≥ danger` | `≥ danger` |

Default (bila belum pernah dikalibrasi): DHT22 warning 30°C / danger 35°C · SMOKE warning 100 ppm / danger 200 ppm.

Contoh kalibrasi: suhu 25–28°C = warning berarti isi *warning=25, danger=28* → 24°C normal, 26°C warning, 30°C danger.

## 2. Workflow

```
Dashboard ──POST /thresholds/form (admin_token)──► calibrateForm()
  → parse 4 angka, cek ADMIN_TOKEN → 401 bila salah
  → Store.SetThresholds(): validasi 0 ≤ warning < danger per sensor → 400 bila salah
  → simpan ke tabel thresholds (upsert DHT22 & SMOKE) + cache di memori
  → 303 redirect /?saved=kalibrasi → banner "Kalibrasi tersimpan."

Ingest berikutnya ──POST /data──► InsertReading() memakai ambang terbaru
  → EvaluateWith(sensor, data, thresholds) → alert masuk tabel alerts bila warning/danger
  → badge status dashboard juga memakai ambang terbaru
```

Kalibrasi tetap berlaku setelah restart (dibaca ulang dari tabel `thresholds` saat `store.Open()`).

## 3. Model Data (perubahan)

```sql
thresholds(sensor_type TEXT PK,  -- 'DHT22' | 'SMOKE'
           warn REAL, danger REAL)
```

Tabel lain tidak berubah. DB lama langsung kompatibel (`CREATE TABLE IF NOT EXISTS`).

## 4. API (perubahan)

| Method | Path | Auth | Keterangan |
|---|---|---|---|
| `POST` | `/thresholds/form` | form `admin_token` | ★ Baru. Field: `temp_warn`, `temp_danger`, `smoke_warn`, `smoke_danger` (angka). Sukses → redirect dashboard; salah token `401`, angka/validasi salah `400` |

Endpoint Fase 1–3 tidak berubah.

## 5. Deploy Ulang

```bash
docker compose up -d --build && curl localhost:8080/health
```

## 6. Cara Cek Fase 4 (checklist)

```bash
TOKEN=$(grep '^ADMIN_TOKEN=' .env | cut -d= -f2-)

# 1. kalibrasi: suhu warning 25, danger 28; asap warning 50, danger 80
curl -s -i -X POST localhost:8080/thresholds/form \
  -d "temp_warn=25&temp_danger=28&smoke_warn=50&smoke_danger=80&admin_token=$TOKEN" | grep -iE '^HTTP|location'

# 2. dashboard menampilkan nilai kalibrasi baru + formnya
curl -s localhost:8080/ | grep -oE 'Kalibrasi sensor|Simpan kalibrasi'

# 3. ingest 26°C → sekarang warning (sebelumnya ok)
curl -s -X POST localhost:8080/data -d '{"device_id":"ESP32-001","api_key":"<key>","sensor_type":"DHT22","data":{"temperature":26}}'
curl -s localhost:8080/alerts   # → alert warning suhu 26.0°C >= 25°C

# 4. nilai tak valid ditolak
curl -s -X POST localhost:8080/thresholds/form \
  -d "temp_warn=30&temp_danger=30&smoke_warn=50&smoke_danger=80&admin_token=$TOKEN"
# → 400 harus 0 <= warning < danger untuk tiap sensor
```

## 7. Batasan

- Hanya DHT22 (`temperature`) & SMOKE (`ppm`); sensor generik tetap `ok`.
- Ambang global untuk semua device (belum per-device).
- Form butuh `ADMIN_TOKEN`, sama seperti tambah device/rotate key — tanpa login/CSRF, untuk jaringan tepercaya.
