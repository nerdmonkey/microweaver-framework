import sys
from unittest.mock import MagicMock

for _name in ("network", "umqtt", "umqtt.simple"):
    sys.modules.setdefault(_name, MagicMock())
