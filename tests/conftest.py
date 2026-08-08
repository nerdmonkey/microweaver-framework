import sys
import types
from unittest.mock import MagicMock

for _name in (
    "network",
    "machine",
    "esp32",
    "dht",
    "urequests",
):
    sys.modules.setdefault(_name, MagicMock())

# umqtt.simple gets a real (if minimal) module rather than a bare MagicMock so
# `except MQTTException` in app.services.mqtt has an actual exception class to
# catch - a Mock attribute isn't a valid except-clause target.
sys.modules.setdefault("umqtt", types.ModuleType("umqtt"))
if "umqtt.simple" not in sys.modules:
    _umqtt_simple = types.ModuleType("umqtt.simple")
    _umqtt_simple.MQTTClient = MagicMock()

    class MQTTException(Exception):
        pass

    _umqtt_simple.MQTTException = MQTTException
    sys.modules["umqtt.simple"] = _umqtt_simple
