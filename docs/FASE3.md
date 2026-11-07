# Fase 3 — Tambah Device & Generate API Key dari Dashboard

> Workflow Fase 3 di atas Fase 2 ([FASE2.md](FASE2.md)): kelola device langsung dari dashboard, tanpa curl dan tanpa JS.

## 1. Ringkasan

- **Tambah device dari dashboard**: form di `GET /` → `POST /devices/form` (form HTML, butuh `ADMIN_TOKEN`).
- **Generate API key baru bila key hilang**: tombol per device → `POST /devices/{id}/rotate` → key lama langsung mati, key baru tampil **sekali** di banner dashboard (atau JSON bila dipanggil via API).
- Tetap tanpa framework/JS: form HTML biasa + redirect `303` ke dashboard.

## 2. Workflow

### 2.1 Tambah device dari dashboard

```
Browser ──GET /──► dashboard (form: device_id, name, admin_token)
Browser ──POST /devices/form──► createDeviceForm():
  → ParseForm, cek admin_token == ADMIN_TOKEN (bila diset) → 401 bila salah
  → validasi device_id (huruf/angka/-_) + name wajib
  → Store.CreateDevice(): NewKey() acak, simpan SHA-256 hash saja
  → 303 redirect /?new_key=<key>
  → dashboard tampil banner "API key baru — salin sekarang…" berisi key
```

### 2.2 Generate API key baru (key hilang)

```
Browser ──POST /devices/{id}/rotate (admin_token)──► rotateKey()
API    ──POST /devices/{id}/rotate (X-Admin-Token)──► rotateKey()
  → cek admin token → 401 bila salah
  → Store.RotateKey(id): UPDATE devices SET api_key_hash = HashKey(key baru)
       → 404 JSON bila device tidak ada
  → key lama langsung tidak bisa ingest; key baru tampil sekali:
       form → 303 banner dashboard; JSON → 200 {"device_id","api_key"}
```

Setelah rotate: pasang key baru di ESP32 (variabel `API_URL`/key di firmware), key lama sudah mati.

## 3. API (perubahan)

| Method | Path | Auth | Keterangan |
|---|---|---|---|
| `POST` | `/devices/form` | form `admin_token` | ★ Baru. Tambah device dari dashboard → redirect banner berisi `api_key` sekali saja. Error tampil sebagai teks (`400`/`401`) |
| `POST` | `/devices/{id}/rotate` | `X-Admin-Token` atau form `admin_token` | ★ Baru. Generate key baru; `404` device tak ada, `401` token salah |

Endpoint Fase 1–2 tidak berubah (`POST /devices`, `GET /devices`, `POST /data`, `GET /devices/{id}/history`, `GET /alerts`, `GET /`, `GET /health`).

## 4. Keamanan

- Kedua endpoint tetap dilindungi `ADMIN_TOKEN` (kosong = terbuka, dev saja) — sama seperti `POST /devices`.
- Server tetap hanya menyimpan hash SHA-256; key baru hanya tampil sekali (banner/JSON), tidak bisa dilihat lagi sesudahnya.
- Catatan: key baru lewat query `?new_key=` di URL dashboard — cukup untuk dashboard lokal/MVP; jangan tambah logging URL bila ini diakses publik.

## 5. Deploy Ulang

```bash
docker compose up -d --build && curl localhost:8080/health
```

## 6. Cara Cek Fase 3 (checklist)

```bash
TOKEN=$(grep '^ADMIN_TOKEN=' .env | cut -d= -f2-)

# 1. tambah device dari dashboard (form) — harus redirect + banner key
curl -s -i -X POST localhost:8080/devices/form \
  -d "device_id=ESP32-003&name=Gudang&admin_token=$TOKEN" | grep -iE 'HTTP/|location'

# 2. ambil key dari banner, ingest pakai key itu harus saved
# 3. rotate via API — key lama mati, key baru saved
KEY=$(curl -s -X POST localhost:8080/devices/ESP32-003/rotate -H "X-Admin-Token: $TOKEN" | python3 -c "import sys,json;print(json.load(sys.stdin)['api_key'])")
curl -s -X POST localhost:8080/data -d "{\"device_id\":\"ESP32-003\",\"api_key\":\"$KEY\",\"sensor_type\":\"DHT22\",\"data\":{\"temperature\":25}}"
# → {"status":"saved"}

# 4. tombol "Generate API key baru" per device ada di dashboard
curl -s localhost:8080/ | grep -oE 'Tambah device|Generate API key baru'
```

## 7. Batasan

- Form dashboard tidak ada CSRF token / login — hanya aman untuk jaringan tepercaya, sama seperti keterbatasan Fase 1–2 (dashboard terbuka).
- Tidak ada daftar/edit/hapus device selain rotate key.
