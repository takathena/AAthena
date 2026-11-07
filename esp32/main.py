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
    wlan.active(True)
    if wlan.isconnected():
        return True
    print("[WiFi] Menghubungkan ke %s ..." % WIFI_SSID)
    wlan.connect(WIFI_SSID, WIFI_PASSWORD)
    for _ in range(WIFI_TIMEOUT):
        if wlan.isconnected():
            print("[WiFi] Terhubung, IP: %s" % wlan.ifconfig()[0])
            return True
        time.sleep(1)
    print("[WiFi] Gagal terhubung")
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


def send_data(data, sensor_type):
    payload = {
        "device_id": DEVICE_ID,
        "api_key": API_KEY,
        "sensor_type": sensor_type,
        "data": data,
    }
    try:
        r = urequests.post(API_URL, data=ujson.dumps(payload),
                           headers={"Content-Type": "application/json"})
        print("[HTTP] %s -> %s" % (sensor_type, r.status_code))
        if r.status_code == 401:
            print("[! ] API key salah — generate key baru dari dashboard")
        r.close()
        return r.status_code == 200
    except Exception as e:
        print("[HTTP] Gagal kirim: %s" % e)
        return False


def main():
    while True:
        if not wlan.isconnected():
            connect_wifi()
            time.sleep(2)
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
