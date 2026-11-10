"""AAguard IoT - FastAPI Pydantic v2 schemas."""
import math
import re
import typing

from pydantic import BaseModel, ConfigDict, Field, field_validator

SENSOR_KEY_PATTERN = re.compile(r'^[a-zA-Z0-9_]{1,32}$')
MAX_SENSOR_KEYS = 32
MAX_SENSOR_STRING_LEN = 64


def validate_sensor_data(data):
    """`data` harus dict datar: key aman, nilai angka finite / bool / string pendek."""
    if not isinstance(data, dict):
        raise ValueError('data harus berupa object')
    if len(data) > MAX_SENSOR_KEYS:
        raise ValueError(f'data maksimal {MAX_SENSOR_KEYS} key')
    for key, value in data.items():
        if not isinstance(key, str) or not SENSOR_KEY_PATTERN.match(key):
            raise ValueError(
                'Key data hanya boleh huruf, angka, underscore (1-32 karakter)')
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError(f"Nilai '{key}' harus angka yang valid (bukan NaN/Infinity)")
            continue
        if isinstance(value, str):
            if len(value) > MAX_SENSOR_STRING_LEN:
                raise ValueError(
                    f"Nilai '{key}' maksimal {MAX_SENSOR_STRING_LEN} karakter")
            continue
        raise ValueError(f"Nilai '{key}' harus angka, boolean, atau string pendek")


def _offline_timeout_before(value):
    """OfflineTimeoutField: '' -> None (mode otomatis)."""
    if value == '':
        return None
    return value


class _Base(BaseModel):
    model_config = ConfigDict(extra='ignore')


class DeviceCreate(_Base):
    device_id: str = Field(..., max_length=64, pattern=r'^[a-zA-Z0-9_\-]+$')
    device_name: str = Field(..., max_length=128)
    device_type: str = Field('ESP32', max_length=32)
    location: str = Field('', max_length=255)
    description: str = Field('', max_length=1000)
    firmware_version: str = Field('', max_length=64)
    expected_interval: int = Field(60, ge=10, le=86400)
    offline_timeout: typing.Optional[int] = Field(None, ge=10, le=604800)
    offline_alert_severity: str = Field('danger', pattern=r'^(info|warning|danger)$')
    alert_rules: typing.Optional[dict] = None

    @field_validator('offline_timeout', mode='before')
    @classmethod
    def check_offline_timeout(cls, v):
        return _offline_timeout_before(v)


class DeviceUpdate(_Base):
    device_name: typing.Optional[str] = Field(None, min_length=1, max_length=128)
    device_type: typing.Optional[str] = Field(None, max_length=32)
    location: typing.Optional[str] = Field(None, max_length=255)
    description: typing.Optional[str] = Field(None, max_length=1000)
    firmware_version: typing.Optional[str] = Field(None, max_length=64)
    latitude: typing.Optional[float] = Field(None, ge=-90, le=90)
    longitude: typing.Optional[float] = Field(None, ge=-180, le=180)
    expected_interval: typing.Optional[int] = Field(None, ge=10, le=86400)
    offline_timeout: typing.Optional[int] = Field(None, ge=10, le=604800)
    offline_alert_severity: typing.Optional[str] = Field(
        None, pattern=r'^(info|warning|danger)$')
    alert_rules: typing.Optional[dict] = None

    @field_validator('offline_timeout', mode='before')
    @classmethod
    def check_offline_timeout(cls, v):
        return _offline_timeout_before(v)


class SensorData(_Base):
    device_id: str = Field(..., max_length=64)
    api_key: str = Field(..., min_length=32, max_length=128)
    sensor_type: str = Field(..., pattern=r'^[A-Za-z0-9_\-]{1,32}$')
    wifi_ssid: str = Field('', max_length=64)
    uptime_seconds: int = Field(0, ge=0, le=10**10)
    data: dict = Field(...)

    @field_validator('data')
    @classmethod
    def check_data(cls, v):
        validate_sensor_data(v)
        return v


class BulkImportItem(_Base):
    device_id: str = Field(..., max_length=64, pattern=r'^[a-zA-Z0-9_\-]+$')
    device_name: str = Field(..., max_length=128)
    device_type: str = Field('ESP32', max_length=32)
    location: str = Field('', max_length=255)
    description: str = Field('', max_length=1000)
    firmware_version: str = Field('', max_length=64)
    offline_timeout: typing.Optional[int] = Field(None, ge=10, le=604800)
    offline_alert_severity: str = Field('danger', pattern=r'^(info|warning|danger)$')

    @field_validator('offline_timeout', mode='before')
    @classmethod
    def check_offline_timeout(cls, v):
        return _offline_timeout_before(v)
