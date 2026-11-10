# Workspace update (schema v17)

## Model
- Dashboard = ruang kerja: memiliki perangkat, anggota, dan bot Telegram sendiri.
- Peran: owner (pemilik), editor, viewer. Admin diperlakukan sebagai owner di semua dashboard.
- Migrasi v17 memindahkan semua perangkat/kartu lama ke dashboard default admin pertama. Idempotent.
- Dashboard baru kosong total (tanpa perangkat, tab, widget).

## Perilaku baru
- User non-admin boleh menambah perangkat di dashboard tempat ia owner/editor.
- Admin: menu dashboard punya "Semua perangkat" (/all) dengan lencana dashboard dan pemilik.
- Telegram per dashboard (Edit Dashboard > Telegram). Token dienkripsi (Fernet), tidak pernah dikirim balik utuh.
  Tanpa konfigurasi, alert memakai bot default .env. Dashboard yang dimatikan = alert tidak dikirim.
- Menghapus user memindahkan perangkat/kartunya ke dashboard admin yang menghapus. Dashboard berisi perangkat tidak bisa dihapus (409).

## Manajemen database (admin)
- Menu "Kelola Data": hapus per rentang tanggal (+ filter tabel/perangkat), pratinjau wajib, opsi backup otomatis.
- Hapus backup satu per satu; backup terbaru dilindungi.
- "Kecilkan file" (VACUUM) terpisah, dengan pengecekan ruang disk.
- audit_log: siapa menghapus/mengubah apa.

## Tombol "Batal"
Akar masalah: "Batal" berkelas `btn btn-secondary modal-close`, dan `.modal-close` dipaksa 36x36px (kelas untuk tombol ikon x).
Perbaikan di static/css/fixes.css.

## Deploy
1. `pip install -r requirements.txt` (menambah `cryptography`).
2. Opsional: set `TELEGRAM_TOKEN_KEY` di .env (kalau kosong diturunkan dari SECRET_KEY).
3. BACKUP database produksi, lalu jalankan; migrasi v17 berjalan otomatis saat start.

## Batasan yang diketahui
- Alert rules global tetap satu untuk semua dashboard.
- Device ID unik global: pesan "Device ID already exists" bisa membocorkan keberadaan ID milik dashboard lain.
- Halaman /alerts dan /device/<id> memakai gabungan semua dashboard yang boleh diakses.
