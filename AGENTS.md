# Workflow Agent

1. Buat/ubah kode sesuai perintah user, sekecil mungkin (skill `ponytail` aktif — hemat token, tanpa fitur di luar permintaan).
2. Setiap perubahan: jalankan `gofmt`, `go vet ./...`, `go test ./...`.
3. Setiap perubahan: **commit** (pesan singkat, mis. `fase2: alert + status dashboard`). Jangan commit `.env`, `data/`, `graphify-out/`.
4. Setiap perubahan: **deploy ulang** — `docker compose up -d --build` (atau `docker compose restart iot` bila hanya config), lalu cek `curl localhost:8080/health`.
5. Lapor ringkas: file berubah, hasil test, status container.
