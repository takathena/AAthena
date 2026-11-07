# Firmware ESP32 — iot-go

MicroPython untuk ESP32. Kirim data DHT22 (+ opsional asap MQ-2) ke `POST /data` setiap 10 detik.

## Sambungan

| Komponen | ESP32 |
|---|---|
| DHT22 DATA | GPIO4 (D4) — 10kΩ pull-up ke 3V3 |
| MQ-2 AO (opsional) | GPIO34 (ADC) — set `SMOKE_PIN = None` bila tidak dipasang |

## Cara pakai

1. Buat device di dashboard iot-go → salin `api_key` (tampil sekali).
2. Salin `secrets.example.py` → `secrets.py`, isi WiFi, `API_URL`, `DEVICE_ID`, `API_KEY`.
3. Upload `main.py` + `secrets.py` ke board (Thonny: Tools → Options → MicroPython; atau `rshell`/`esptool`).
4. Reset board → cek dashboard: device muncul, data masuk, badge status ikut kalibrasi.

Payload yang dikirim: `{"device_id","api_key","sensor_type":"DHT22","data":{"temperature":..,"humidity":..}}` (dan `SMOKE`/`{"ppm":..}` bila MQ-2 dipasang).

Key hilang / `401 API key salah` → Generate API key baru dari dashboard, update `secrets.py`, upload ulang.
