import time

try:
    import ujson as json
except ImportError:
    import json


def format_local_timestamp(epoch_seconds, offset_minutes):
    """ISO 8601 timestamp with UTC offset, e.g. "2026-08-12T18:13:33+08:00".

    MicroPython's `time` module has no `strftime`/zoneinfo, so the offset is
    applied by hand to `time.gmtime()` rather than relying on a tz database.
    """
    year, month, day, hour, minute, second = time.gmtime(
        epoch_seconds + offset_minutes * 60
    )[:6]
    sign = "+" if offset_minutes >= 0 else "-"
    offset_hours, offset_mins = divmod(abs(offset_minutes), 60)
    return "{:04d}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}{}{:02d}:{:02d}".format(
        year, month, day, hour, minute, second, sign, offset_hours, offset_mins
    )


def to_payload(**fields):
    """Serialize named reading fields into the str publish_message expects.

    Adapter `read()` shapes vary (DHT22Adapter returns a bare tuple,
    actuator/indicator adapters return bool/int) so there's no single dict
    shape to standardize on at the adapter level. Instead the caller names
    each field when building the message, e.g.
    `to_payload(temperature=t, humidity=h)`, and this is the one place that
    turns that into JSON, instead of every adapter call site reinventing
    `json.dumps`.
    """
    return json.dumps(fields)
