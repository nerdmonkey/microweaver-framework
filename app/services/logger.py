import time

try:
    import ujson as json
except ImportError:
    import json

_LEVELS = {"debug": 10, "info": 20, "warning": 30, "error": 40}


class LogService:
    def __init__(self, format="json", level="info"):
        self.format = format
        self.level = level

    def log(self, event, level="info", **fields):
        if _LEVELS.get(level, 20) < _LEVELS.get(self.level, 20):
            return
        entry = {"event": event, "level": level, "ts": time.time()}
        entry.update(fields)
        print(self._render(entry))

    def _render(self, entry):
        if self.format == "kv":
            return " ".join(
                "{}={}".format(key, self._kv_value(value))
                for key, value in entry.items()
            )
        return json.dumps(entry)

    def _kv_value(self, value):
        if isinstance(value, str) and " " in value:
            return '"{}"'.format(value)
        return value
