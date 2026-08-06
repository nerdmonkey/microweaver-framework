import time

try:
    import ujson as json
except ImportError:
    import json


class LogService:
    def __init__(self, format="json"):
        self.format = format

    def log(self, event, level="info", **fields):
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
