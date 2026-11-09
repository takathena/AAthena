"""
NEXUS IoT - Input Validation Schemas
Batch 8: + Bulk import schema
"""
import math
import re

from marshmallow import Schema, fields, validate, ValidationError

SENSOR_KEY_PATTERN = re.compile(r'^[a-zA-Z0-9_]{1,32}$')
SENSOR_TYPE_PATTERN = re.compile(r'^[A-Za-z0-9_\-]{1,32}$')
MAX_SENSOR_KEYS = 32
MAX_SENSOR_STRING_LEN = 64


def validate_sensor_data(data):
    """`data` harus dict datar: key aman, nilai angka finite / bool / string pendek."""
    if not isinstance(data, dict):
        raise ValidationError('data harus berupa object')
    if len(data) > MAX_SENSOR_KEYS:
        raise ValidationError(f'data maksimal {MAX_SENSOR_KEYS} key')
    for key, value in data.items():
        if not isinstance(key, str) or not SENSOR_KEY_PATTERN.match(key):
            raise ValidationError(
                'Key data hanya boleh huruf, angka, underscore (1-32 karakter)')
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            if isinstance(value, float) and not math.isfinite(value):
                raise ValidationError(f"Nilai '{key}' harus angka yang valid (bukan NaN/Infinity)")
            continue
        if isinstance(value, str):
            if len(value) > MAX_SENSOR_STRING_LEN:
                raise ValidationError(
                    f"Nilai '{key}' maksimal {MAX_SENSOR_STRING_LEN} karakter")
            continue
        raise ValidationError(f"Nilai '{key}' harus angka, boolean, atau string pendek")


class OfflineTimeoutField(fields.Field):
    """`offline_timeout` detik: None/'' (mode otomatis) atau int 10..604800.

    Dipakai POST /devices, PUT /devices/<id>, dan bulk-import supaya aturannya
    persis sama di semua jalur. Batas ≥ `expected_interval` tetap dicek di
    handler karena butuh nilai interval dari payload/DB.
    """

    OFFLINE_TIMEOUT_MIN = 10
    OFFLINE_TIMEOUT_MAX = 604800

    def _deserialize(self, value, attr, data, **kwargs):
        if value is None or value == '':
            return None
        try:
            ival = int(value)
        except (TypeError, ValueError):
            raise ValidationError(
                'Offline Timeout harus berupa angka atau dikosongkan')
        if ival < self.OFFLINE_TIMEOUT_MIN:
            raise ValidationError(
                f'Offline Timeout minimal {self.OFFLINE_TIMEOUT_MIN} detik. '
                'Kosongkan untuk mode otomatis.')
        if ival > self.OFFLINE_TIMEOUT_MAX:
            raise ValidationError(
                f'Offline Timeout maksimal {self.OFFLINE_TIMEOUT_MAX} detik (7 hari).')
        return ival


class DeviceCreateSchema(Schema):
    device_id = fields.Str(
        required=True,
        validate=[
            validate.Length(min=1, max=64),
            validate.Regexp(r'^[a-zA-Z0-9_\-]+$',
                            error='Device ID hanya boleh huruf, angka, dash, dan underscore')
        ]
    )
    device_name = fields.Str(required=True, validate=validate.Length(min=1, max=128))
    device_type = fields.Str(load_default='ESP32', validate=validate.Length(max=32))
    location = fields.Str(load_default='', validate=validate.Length(max=255))
    description = fields.Str(load_default='', validate=validate.Length(max=1000))
    firmware_version = fields.Str(load_default='', validate=validate.Length(max=64))
    expected_interval = fields.Int(load_default=60, validate=validate.Range(min=10, max=86400))
    offline_timeout = OfflineTimeoutField(load_default=None, allow_none=True)
    offline_alert_severity = fields.Str(
        load_default='danger',
        validate=validate.OneOf(['info', 'warning', 'danger'])
    )
    alert_rules = fields.Dict(load_default=None, allow_none=True)


class DeviceUpdateSchema(Schema):
    device_name = fields.Str(validate=validate.Length(min=1, max=128))
    device_type = fields.Str(validate=validate.Length(max=32))
    location = fields.Str(validate=validate.Length(max=255))
    description = fields.Str(validate=validate.Length(max=1000))
    firmware_version = fields.Str(validate=validate.Length(max=64))
    latitude = fields.Float(validate=validate.Range(min=-90, max=90))
    longitude = fields.Float(validate=validate.Range(min=-180, max=180))
    # None = kembali ke mode otomatis (auto-detect)
    expected_interval = fields.Int(allow_none=True, validate=validate.Range(min=10, max=86400))
    offline_timeout = OfflineTimeoutField(allow_none=True)
    offline_alert_severity = fields.Str(validate=validate.OneOf(['info', 'warning', 'danger']))
    alert_rules = fields.Dict(allow_none=True)


class SensorDataSchema(Schema):
    device_id = fields.Str(required=True, validate=validate.Length(min=1, max=64))
    api_key = fields.Str(required=True, validate=validate.Length(min=32, max=128))
    sensor_type = fields.Str(
        required=True,
        validate=validate.Regexp(
            SENSOR_TYPE_PATTERN,
            error='sensor_type hanya boleh huruf, angka, dash, underscore (1-32 karakter)')
    )
    wifi_ssid = fields.Str(load_default='', validate=validate.Length(max=64))
    uptime_seconds = fields.Int(load_default=0, validate=validate.Range(min=0, max=10**10))
    data = fields.Dict(required=True, validate=validate_sensor_data)


class BulkImportItemSchema(Schema):
    device_id = fields.Str(
        required=True,
        validate=[
            validate.Length(min=1, max=64),
            validate.Regexp(r'^[a-zA-Z0-9_\-]+$',
                            error='Device ID hanya boleh huruf, angka, dash, dan underscore')
        ]
    )
    device_name = fields.Str(required=True, validate=validate.Length(min=1, max=128))
    device_type = fields.Str(load_default='ESP32', validate=validate.Length(max=32))
    location = fields.Str(load_default='', validate=validate.Length(max=255))
    description = fields.Str(load_default='', validate=validate.Length(max=1000))
    firmware_version = fields.Str(load_default='', validate=validate.Length(max=64))
    offline_timeout = OfflineTimeoutField(load_default=None, allow_none=True)
    offline_alert_severity = fields.Str(
        load_default='danger',
        validate=validate.OneOf(['info', 'warning', 'danger'])
    )


device_create_schema = DeviceCreateSchema()
device_update_schema = DeviceUpdateSchema()
sensor_data_schema = SensorDataSchema()
bulk_import_item_schema = BulkImportItemSchema()