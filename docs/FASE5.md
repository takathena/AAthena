# Fase 5 — Kalibrasi Per-Device (Override Global)

> Di atas Fase 4 ([FASE4.md](FASE4.md)): kalibrasi bisa global (default semua device) **atau** khusus per device, seperti Nexus IoT.

## 1. Konsep

```
Ambang efektif(device) = kalibrasi device sendiri   bila device punya kalibrasi
                       = kalibrasi global           bila device tidak punya kalibrasi
```

Ada kalibrasi device → **global tidak dipakai** untuk device itu (walau hanya suhu yang diubah, satu set DHT22+SMOKE disimpan per device). Hapus kalibrasi device → kembali ikut global.

Contoh: global suhu warning 25°C. Device `Ruang Server` diset warning 20°C → 21°C memicu warning di device itu, tapi device lain (tanpa kalibrasi sendiri) tetap `ok` di 21°C.

## 2. Workflow

```
Dashboard per device ──POST /devices/{id}/calibrate (admin_token)──► SetDeviceThresholds()
  → validasi 0 ≤ warning < danger, device harus ada (404 bila tidak)
  → upsert 2 baris ke device_thresholds (DHT22 + SMOKE)
  → ingest berikutnya pakai ambang device ini; badge status juga begitu

Dashboard per device ──POST /devices/{id}/calibrate/clear (admin_token)──► ClearDeviceThresholds()
  → hapus baris device_thresholds → device kembali ikut global
```

Urutan evaluasi saat ingest (`InsertReading`): verifikasi key → ambil ambang efektif device → simpan reading + alert (bila warning/danger) dalam satu transaksi.

## 3. Model Data (perubahan)

```sql
device_thresholds(device_id TEXT, sensor_type TEXT,  -- 'DHT22' | 'SMOKE'
                  warn REAL, danger REAL,
                  PRIMARY KEY(device_id, sensor_type))
```

Tabel global `thresholds` (Fase 4) tidak berubah. Dashboard menampilkan label per device: **Kalibrasi: sendiri** atau **ikut global**, beserta range efektifnya.

## 4. API (perubahan)

| Method | Path | Auth | Keterangan |
|---|---|---|---|
| `POST` | `/devices/{id}/calibrate` | form `admin_token` | ★ Baru. Field sama seperti kalibrasi global (`temp_warn`, `temp_danger`, `smoke_warn`, `smoke_danger`). `404` device tak ada, `401` token salah, `400` angka/validasi salah |
| `POST` | `/devices/{id}/calibrate/clear` | form `admin_token` | ★ Baru. Hapus kalibrasi device → ikut global lagi |

Endpoint Fase 1–4 tidak berubah (`POST /thresholds/form` tetap untuk kalibrasi global).

## 5. Deploy Ulang

```bash
docker compose up -d --build && curl localhost:8080/health
```

## 6. Cara Cek Fase 5 (checklist)

```bash
TOKEN=$(grep '^ADMIN_TOKEN=' .env | cut -d= -f2-)

# 1. global tetap 25/28°C (Fase 4). Set kalibrasi khusus ESP32-001: warning 20°C
curl -s -i -X POST localhost:8080/devices/ESP32-001/calibrate \
  -d "temp_warn=20&temp_danger=22&smoke_warn=10&smoke_danger=20&admin_token=$TOKEN" | grep -iE '^HTTP|location'

# 2. 21°C di ESP32-001 → warning (kalibrasi sendiri)
curl -s -X POST localhost:8080/data -d '{"device_id":"ESP32-001","api_key":"<key1>","sensor_type":"DHT22","data":{"temperature":21}}'
curl -s localhost:8080/alerts | head -c 300   # → warning suhu 21.0°C >= 20°C

# 3. 21°C di device lain (tanpa kalibrasi) → ok, tanpa alert baru

# 4. dashboard: ESP32-001 berlabel "sendiri", device lain "ikut global"
curl -s localhost:8080/ | grep -oE 'Kalibrasi device ini: [^<]+'

# 5. hapus kalibrasi → kembali ikut global
curl -s -i -X POST localhost:8080/devices/ESP32-001/calibrate/clear \
  -d "admin_token=$TOKEN" | grep -iE '^HTTP|location'
```

## 7. Batasan

- Kalibrasi device disimpan sebagai satu set lengkap (DHT22+SMOKE) — belum per-sensor terpisah.
- Butuh `ADMIN_TOKEN` seperti fitur dashboard lain; tanpa login/CSRF (jaringan tepercaya).
