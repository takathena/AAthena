# Dashboard UI (referensi Nexus IoT)

Tampilan dashboard mengikuti gaya Nexus IoT (branch `main`: sidebar/topbar, metric cards, kontrol 36px, tema dark/light) — disederhanakan jadi satu halaman tanpa framework/JS baru.

## Struktur halaman `GET /`

- **Topbar lengket**: logo + nama, toggle tema (tersimpan di `localStorage`, ikut `prefers-color-scheme`).
- **Metric cards**: Total device · Normal · Warning · Danger (dihitung dari status reading terakhir tiap device).
- **Section Tambah device** & **Kalibrasi sensor (global)**: form satu baris kartu.
- **Kartu device** (grid responsif): nama, ID, terakhir terlihat, badge status, reading terakhir besar, `<details>` Riwayat 10 terakhir + Kelola device (rotate key, kalibrasi sendiri/global).
- **Section Alert terbaru**: tabel alert 20 terakhir dengan badge level.
- Refresh otomatis 30 detik (`<meta refresh>`), responsif ≤760px jadi 1 kolom.

Fungsi & endpoint tidak berubah — hanya tampilan.
