# Redesain — Fase 0 (Fondasi): status

## Ditambahkan
- static/css/components.css: tombol (primer, sekunder/ghost, bahaya, ikon), badge, chip, tabs, menu ⋯, dialog konfirmasi, drawer, empty state, kelas .nx-hidden. Memakai token yang sudah ada.
- static/js/ui.js: AAGuardUI.applyNeeds() untuk atribut data-needs, serta helper dialog, drawer, dan menu. Tanpa penyimpanan browser.
- tests/test_phase6_fondasi.py: tes struktur CSS/JS/template dan logika applyNeeds (Node.js).

## Diubah
- templates/dashboard.html: memuat components.css dan ui.js (sebelum dashboard.js).
- static/js/dashboard.js: memanggil AAGuardUI.applyNeeds() setelah peran dashboard aktif diketahui. Logika is-viewer lama tetap ada.

## Belum (sisa Fase 0)
- Memecah dashboard.js (4.200 baris) menjadi modul per halaman.
- Menyatukan logika desktop dan mobile (mobile.js).
- Memperluas router hash untuk #settings/<tab> dan #device/<id>.
- Memindahkan markup lama ke data-needs dan menghapus selector body.is-viewer / is-non-admin.
- Menghapus !important di fixes.css dan unified.css secara bertahap.

## Verifikasi
- Tes Fase 0 lolos (8/8) dengan runner pengganti, karena pytest tidak tersedia di sandbox.
- Sintaks ui.js dan dashboard.js valid (node --check).
- Belum diuji di browser dan belum menjalankan suite penuh (make test) di mesin Anda.

# Redesain — Fase 1 (Navigasi dan Pengaturan): status

## Diubah
- templates/dashboard.html: sidebar utama tinggal 6 menu kerja. Footer hanya berisi Pengaturan dan Logout. Sembilan tombol admin/tema/info lama dipindah ke #legacyActions (tersembunyi) agar handler lama tetap terikat. Validator hash menerima #settings dan #settings/<tab>.
- static/js/dashboard.js: DASHBOARD_SECTIONS menambah 'settings'; router membaca #settings/<tab>; sorotan sidebar dan binding navigasi memakai `.sidebar` (bukan `.sidebar-nav`) agar Pengaturan ikut.

## Ditambahkan
- templates/partials/settings_section.html: halaman Pengaturan dengan tab Umum, Notifikasi, Alert Rules, Pengguna, Data & Backup, Impor, Sistem. Tab admin diberi data-needs="admin".
- static/js/settings.js: mengatur tab, menyembunyikan tab admin untuk non-admin, dan meneruskan klik tombol ke tombol lama lewat data-proxy.
- static/css/components.css: gaya halaman Pengaturan dan kartu baris.
- tests/test_phase6_pengaturan.py: 11 tes struktur (sidebar, proxy, tab, gerbang admin).

## Belum (sisa Fase 1 dan Fase 0)
- Topbar (breadcrumb, pusat notifikasi, palet perintah Ctrl/⌘+K) belum diubah.
- Menu akun popover belum ada; Tema dan Ganti Password dipindah ke tab Umum.
- Tab "Dashboard ini" (Edit Dashboard, Bagikan, Telegram) belum dibuat; modalnya masih ada.
- Modal lama (22 modal di modals.html) belum dihapus. Akan dihapus setelah halaman penggantinya diuji.
- Tab Pengaturan yang masih memakai modal (Notifikasi, Alert Rules, Pengguna, Data & Backup, Impor) membuka modal lama, bukan halaman.
- Pecah dashboard.js dan satukan logika desktop/mobile (Fase 0).
- Mobile (mobile.js dan /mobile) belum disentuh.

## Verifikasi
- 19 tes struktur lolos dengan runner pengganti (Fase 0: 8, Fase 1: 11).
- Sintaks inline script dan dashboard.js/settings.js valid (node --check); template Jinja terparse.
- Belum diuji di browser; belum menjalankan `make test` penuh.

# Redesain — Fase 2 (Kelola Pengguna): status

## Ditambahkan
- static/js/users.js: daftar pengguna langsung tampil di Pengaturan › Pengguna; tambah dan edit lewat laci kanan (X + Simpan saja); hapus lewat dialog Batal | Hapus tanpa X; konfirmasi "Buang perubahan?" bila ada isian belum tersimpan; Escape di laci yang berubah juga meminta konfirmasi.
- Pencarian pengguna dan menu ⋯ per baris (Edit, Hapus). Hapus tidak tersedia untuk akun sendiri.
- Event `aaguard:settings-tab` dari settings.js agar daftar dimuat saat tab dibuka.
- Peran: User dan Admin (is_admin yang sudah ada).

## Belum (menunggu Paket A di review)
- Peran Moderator dan izin absensi (kolom role, tabel user_permissions, endpoint permissions, penegakan di API/chat/UI). Ini perubahan backend dan belum dikerjakan.
- Tombol Salin kredensial dan pembuatan password otomatis.
- Dialog hapus belum menyebut jumlah dashboard secara spesifik.
- userModal lama dan fungsi openUserManagementModal masih ada di kode, tetapi tidak ada lagi tombol yang membukanya. Akan dihapus setelah uji di browser.

## Verifikasi
- 27 tes struktur lolos (Fase 0: 8, Fase 1: 11, Fase 2: 8) dengan runner pengganti.
- Sintaks JS, inline script, dan template Jinja valid.
- Belum diuji di browser.
