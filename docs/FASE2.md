# Fase 2 — Alert & Dashboard Status (iot-go)

> Dokumen workflow lengkap aplikasi setelah Fase 2. Fase 1 (ingest → simpan → dashboard) ada di [FASE1.md](FASE1.md); dokumen ini hanya yang berubah/menambah di Fase 2.

## 1. Ringkasan

Fase 2 menambah **alert ambang batas sensor** di atas aplikasi Fase 1, tanpa halaman, framework, atau service baru:

- Setiap data masuk dievaluasi: suhu DHT22 dan asap SMOKE dibandingkan ke ambang warning/danger.
- Yang melewati ambang disimpan sebagai **riwayat alert** (tabel `alerts`) dan tampil di dashboard yang sama, plus endpoint JSON `GET /alerts`.
- Dashboard menampilkan **badge status per device** (`ok` / `warning` / `danger`) dari reading terakhirnya.

## 2. Arsitektur

```
                 ┌─────────────── iot-go (:8080) ───────────────┐
 ESP32 ─POST /data─► internal/api          internal/store        │
                 │  (HTTP, tanpa SQL)  ──► (semua SQL)            │
                 │                            │                   │
 Browser ─GET /──┘                            ▼                   │
                                   SQLite: devices, sensor_data, alerts
                 └────────────────────────────────────────────────┘
```

| Komponen | File | Peran Fase 2 |
|---|---|---|
| Entry | `main.go` | Tidak berubah. `PORT`, `DB_PATH`, `ADMIN_TOKEN` dari env. |
| API | `internal/api/api.go` | Route baru `GET /alerts`; template dashboard ditambah badge status + tabel alert. |
| Store | `internal/store/store.go` | Tambah `Evaluate()`, tabel `alerts`, `ListAlerts()`, insert alert di TX ingest. |
| Deploy | `Dockerfile`, `docker-compose.yml` | Tidak berubah. 1 service `iot`, volume `./data`, user `10001`. |

## 3. Ambang Batas

Konstanta di `internal/store/store.go` (global untuk semua device):

| Sensor (`sensor_type`) | Field di `data` | Warning | Danger |
|---|---|---|---|
| `DHT22` | `temperature` (°C) | ≥ 30°C | ≥ 35°C |
| `SMOKE` | `ppm` | ≥ 100 ppm | ≥ 200 ppm |

Aturan `Evaluate(sensorType, data)`:

- `sensor_type` tidak dikenal / `data` bukan JSON angka → `ok` (tidak ada alert).
- `data` di bawah warning → `ok`. Di antara warning–danger → `warning`. Di atas danger → `danger`, dengan pesan mis. `suhu 36.0°C >= 35°C`.

## 4. Workflow Lengkap

### 4.1 Provisioning device (tetap seperti Fase 1)

```
Admin ──POST /devices (X-Admin-Token)──► createDevice()
  → validasi device_id (huruf/angka/-/_) + field wajib
  → Store.CreateDevice(): NewKey() acak → simpan SHA-256 hash saja
  → balas 201 {device_id, api_key}   ← plain-text HANYA di sini, sekali saja
```

### 4.2 Ingest + evaluasi alert (perubahan Fase 2 ditandai ★)

```
ESP32 ──POST /data {device_id, api_key, sensor_type, data}──► ingest()
  → decodeBody() maks 64 KB, field wajib
  → Store.InsertReading() [satu transaksi]:
      1. cari device → 404 bila tak ada
      2. HashKey(api_key) vs hash tersimpan, constant-time → 401 bila salah
      3. INSERT sensor_data (timestamp UTC RFC3339)
  ★ 4. Evaluate(sensor_type, data) → bila warning/danger:
         INSERT alerts(device_id, sensor_type, level, message, data, timestamp)
      5. UPDATE devices.last_seen
  → COMMIT → 200 {"status":"saved"}
```

Catatan ★: alert ditulis di transaksi yang sama dengan reading — tidak ada reading tanpa alert-nya, dan sebaliknya.

### 4.3 Membaca alert & status

```
Browser ──GET /──► dashboard():
  → ListDevices() + History(device, 10) per device
  → status device = Evaluate(reading terakhir)   ★
  → ListAlerts(20)                                ★
  → render: badge ok/warning/danger per device + tabel "Alert terbaru"

Siapa pun ──GET /alerts?limit=50──► JSON daftar alert, terbaru dulu (maks 1000)
```

### 4.4 Urutan end-to-end (contoh)

```
1. POST /devices            → catat api_key (sekali saja)
2. POST /data DHT22 36°C    → tersimpan + alert danger "suhu 36.0°C >= 35°C"
3. POST /data SMOKE 120 ppm → tersimpan + alert warning "asap 120 ppm >= 100 ppm"
4. POST /data DHT22 25°C    → tersimpan, tanpa alert (ok)
5. GET /alerts              → 2 alert (warning, danger), terbaru dulu
6. GET /                    → device berstatus warning (reading terakhir SMOKE),
                              tabel alert berisi kedua alert di atas
```

## 5. Model Data (perubahan)

```sql
alerts(id INTEGER PK AUTOINCREMENT, device_id TEXT, sensor_type TEXT,
       level TEXT,        -- 'warning' | 'danger'
       message TEXT,      -- mis. 'suhu 36.0°C >= 35°C'
       data TEXT,         -- payload mentah saat alert terjadi
       timestamp TEXT)    -- UTC RFC3339
```

Tabel Fase 1 (`devices`, `sensor_data`) tidak berubah. Tabel dibuat otomatis `CREATE TABLE IF NOT EXISTS` saat startup — DB lama langsung kompatibel, tanpa migrasi manual.

## 6. API (perubahan)

| Method | Path | Keterangan |
|---|---|---|
| `GET` | `/alerts?limit=50` | ★ Baru. Daftar alert terbaru dulu. `limit` 1–1000, selain itu `400`. Response: array `{id, device_id, sensor_type, level, message, data, timestamp}` (kosong = `null` bila belum ada alert) |
| `GET` | `/` | Tambah badge status per device + tabel Alert terbaru (20) |
| lain | — | Tetap seperti Fase 1 (`/devices`, `/data`, `/devices/{id}/history`, `/health`) |

## 7. Konfigurasi

Tidak ada env baru. Ambang masih konstanta di kode (bila nanti perlu per-device/env, ubah konstanta `TempWarn/TempDanger/SmokeWarn/SmokeDanger` di `internal/store/store.go`).

## 8. Deploy Ulang

Setiap ada perubahan kode:

```bash
docker compose up -d --build   # rebuild image + restart container
docker compose ps              # pastikan (healthy)
curl localhost:8080/health     # → {"status":"ok"}
```

Hanya perubahan `.env` (tanpa rebuild): `docker compose restart iot`.

## 9. Cara Cek Fase 2 (checklist)

```bash
# 0. health
curl localhost:8080/health

# 1. buat device, catat api_key
TOKEN=$(grep '^ADMIN_TOKEN=' .env | cut -d= -f2-)
curl -X POST localhost:8080/devices -H "X-Admin-Token: $TOKEN" \
  -d '{"device_id":"ESP32-001","name":"Ruang Server"}'

# 2. kirim suhu danger + asap warning
curl -X POST localhost:8080/data -d '{"device_id":"ESP32-001","api_key":"<key>","sensor_type":"DHT22","data":{"temperature":36}}'
curl -X POST localhost:8080/data -d '{"device_id":"ESP32-001","api_key":"<key>","sensor_type":"SMOKE","data":{"ppm":120}}'

# 3. riwayat alert harus berisi 2 baris (danger, warning)
curl localhost:8080/alerts

# 4. dashboard: badge status + tabel Alert terbaru
curl localhost:8080/ | grep -E 'badge|Alert terbaru'
```

Hasil test di container (2026-11-07): semua langkah lolos — alert danger/warning tersimpan dan tampil di `/alerts` dan dashboard.

## 10. Batasan yang Diketahui

- Ambang global; belum bisa diubah per device / lewat env.
- Belum ada notifikasi eksternal (email/chat/webhook) — alert hanya di dashboard + API.
- Batasan Fase 1 tetap berlaku: tanpa login, tanpa HTTPS, tanpa retensi/backup otomatis.
