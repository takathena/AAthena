"""
iot-go — Firmware ESP32 (MicroPython)
Sensor: DHT22 (suhu+kelembaban) di GPIO4, opsional MQ-2 asap di GPIO34 (ADC)
Kirim POST /data ke server iot-go setiap SEND_INTERVAL detik.

Upload: salin secrets.example.py -> secrets.py, isi, lalu upload main.py + secrets.py
ke board (Thonny / esptool / rshell). secrets.py JANGAN di-commit.
"""

import machine
import dht
import time
import network
import urequests
import ujson

try:
    from secrets import WIFI_SSID, WIFI_PASSWORD, API_URL, DEVICE_ID, API_KEY
except ImportError:
    raise RuntimeError(
        "secrets.py tidak ditemukan. Salin secrets.example.py menjadi "
        "secrets.py lalu isi WIFI_SSID, WIFI_PASSWORD, API_URL, DEVICE_ID, API_KEY."
    )

DHT_PIN = 4            # GPIO4 -> pin D4 DHT22
SMOKE_PIN = 34         # GPIO34 ADC -> MQ-2 AO (isi None bila tidak dipasang)
SEND_INTERVAL = 10     # detik antar pengiriman
WIFI_TIMEOUT = 20      # detik tunggu WiFi

dht_sensor = dht.DHT22(machine.Pin(DHT_PIN))
smoke_adc = machine.ADC(machine.Pin(SMOKE_PIN)) if SMOKE_PIN else None
if smoke_adc:
    smoke_adc.atten(machine.ADC.ATTN_11DB)

wlan = network.WLAN(network.STA_IF)


def connect_wifi():
    if wlan.isconnected():
        return True
    # Reset state WiFi dulu — connect() tanpa ini memicu "Wifi Internal State Error".
    try:
        wlan.disconnect()
    except Exception:
        pass
    try:
        if not wlan.active():
            wlan.active(True)
    except Exception as e:
        print("[WiFi] Gagal aktifkan radio: %s" % e)
        return False
    print("[WiFi] Menghubungkan ke %s ..." % WIFI_SSID)
    try:
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)
    except OSError as e:
        print("[WiFi] connect() error: %s — coba lagi nanti" % e)
        return False
    for _ in range(WIFI_TIMEOUT):
        if wlan.isconnected():
            print("[WiFi] Terhubung, IP: %s" % wlan.ifconfig()[0])
            return True
        time.sleep(1)
    print("[WiFi] Gagal terhubung (cek SSID/password/jarak)")
    try:
        wlan.disconnect()
    except Exception:
        pass
    return False


def read_sensors():
    data = {}
    try:
        dht_sensor.measure()
        data["temperature"] = round(dht_sensor.temperature(), 1)
        data["humidity"] = round(dht_sensor.humidity(), 1)
    except Exception as e:
        print("[DHT22] Gagal baca: %s" % e)
        return None
    if smoke_adc:
        # Aproksimasi kasar ADC->ppm; kalibrasi ulang bila perlu presisi.
        data["ppm"] = int(smoke_adc.read() * 500 / 4095)
    return data


def _post_https(url, body):
    """POST manual via socket+TLS — urequests MicroPython tidak support https://.

    Cocok untuk domain di balik Cloudflare Tunnel (edge selalu https).
    """
    import socket
    import ssl
    rest = url[8:]  # buang https://
    if "/" in rest:
        hostport, path = rest.split("/", 1)
        path = "/" + path
    else:
        hostport, path = rest, "/data"
    if ":" in hostport:
        host, port = hostport.rsplit(":", 1)
        port = int(port)
    else:
        host, port = hostport, 443
    s = socket.socket()
    s.connect((host, port))
    try:
        s = ssl.wrap_socket(s, server_hostname=host, cert_reqs=ssl.CERT_NONE)
    except TypeError:
        s = ssl.wrap_socket(s, server_hostname=host)
    req = ("POST %s HTTP/1.1\r\nHost: %s\r\nContent-Type: application/json\r\n"
           "Content-Length: %d\r\nConnection: close\r\n\r\n" % (path, host, len(body))) + body
    s.send(req.encode())
    resp = s.recv(2048).decode()
    s.close()
    return int(resp.split(" ")[1])  # status code, mis. "HTTP/1.1 200 OK"


def send_data(data, sensor_type):
    payload = {
        "device_id": DEVICE_ID,
        "api_key": API_KEY,
        "sensor_type": sensor_type,
        "data": data,
    }
    body = ujson.dumps(payload)
    try:
        if API_URL.startswith("https://"):
            status = _post_https(API_URL, body)
        else:
            r = urequests.post(API_URL, data=body,
                               headers={"Content-Type": "application/json"})
            status = r.status_code
            r.close()
        print("[HTTP] %s -> %s" % (sensor_type, status))
        if status == 401:
            print("[! ] API key salah — generate key baru dari dashboard")
        return status == 200
    except Exception as e:
        print("[HTTP] Gagal kirim: %s" % e)
        return False


def main():
    while True:
        if not wlan.isconnected():
            connect_wifi()
            time.sleep(5)  # backoff — jangan hammer connect(), bikin state error
            continue
        data = read_sensors()
        if data is not None:
            if "ppm" in data:
                send_data({"temperature": data["temperature"],
                           "humidity": data["humidity"]}, "DHT22")
                send_data({"ppm": data["ppm"]}, "SMOKE")
            else:
                send_data(data, "DHT22")
        time.sleep(SEND_INTERVAL)


main()
