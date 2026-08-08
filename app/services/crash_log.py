import os
import time

try:
    import ujson as json
except ImportError:
    import json


class CrashLogService:
    def __init__(self, path="crash.json", enabled=True, max_bytes=4096):
        self.path = path
        self.enabled = enabled
        self.max_bytes = max_bytes

    def write(self, event, **fields):
        if not self.enabled:
            return
        entry = {"event": event, "ts": time.time()}
        entry.update(fields)
        serialized = json.dumps(entry)
        if len(serialized) > self.max_bytes:
            serialized = self._shrink(entry)
        try:
            with open(self.path, "w") as crash_file:
                crash_file.write(serialized)
        except Exception as e:
            print("Failed to persist crash log:", e)

    def _shrink(self, entry):
        """Truncate the largest string field(s) until entry fits max_bytes.

        Repeated tracebacks/error messages are the fields most likely to
        grow without bound, so the longest string field is cut first. A
        field already at or below the marker's own length offers nothing
        left to cut, so it's skipped — guaranteeing the loop terminates
        even when max_bytes is too small to fit everything.
        """
        entry = dict(entry)
        marker = "...[truncated]"
        while len(json.dumps(entry)) > self.max_bytes:
            key, value = max(
                (
                    (k, v)
                    for k, v in entry.items()
                    if isinstance(v, str) and len(v) > len(marker)
                ),
                key=lambda item: len(item[1]),
                default=(None, None),
            )
            if key is None:
                break
            overshoot = len(json.dumps(entry)) - self.max_bytes
            cut = min(len(value), overshoot + len(marker))
            cut = max(cut, 1)
            entry[key] = value[: max(len(value) - cut, 0)] + marker
        return json.dumps(entry)

    def read(self):
        try:
            with open(self.path, "r") as crash_file:
                return json.load(crash_file)
        except Exception:
            return None

    def clear(self):
        try:
            os.remove(self.path)
        except Exception as e:
            print("Failed to clear crash log:", e)
