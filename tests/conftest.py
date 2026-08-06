import sys
from unittest.mock import MagicMock

for _name in ("network", "umqtt", "umqtt.simple", "machine", "esp32"):
    sys.modules.setdefault(_name, MagicMock())
