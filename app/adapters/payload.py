try:
    import ujson as json
except ImportError:
    import json


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
