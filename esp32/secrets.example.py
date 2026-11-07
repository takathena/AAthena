# Salin menjadi secrets.py (folder sama dengan main.py), isi, upload ke board.
# JANGAN commit secrets.py — sudah di .gitignore.

WIFI_SSID = "GANTI_DENGAN_NAMA_WIFI"
WIFI_PASSWORD = "GANTI_DENGAN_PASSWORD_WIFI"

# Endpoint ingest iot-go (ganti IP server kamu)
# https:// didukung via socket+TLS manual (cocok untuk Cloudflare Tunnel).
# http://SERVER:8080/data juga bisa (urequests biasa).
API_URL = "https://GANTI_DENGAN_DOMAIN_TUNNEL/data"

# Harus sama persis dengan device yang dibuat di dashboard
DEVICE_ID = "ESP32-001"

# API key device — tampil sekali saat device dibuat / generate key baru
API_KEY = "GANTI_DENGAN_API_KEY_DEVICE"
