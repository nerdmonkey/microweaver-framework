import os
import time

try:
    import ujson as json
except ImportError:
    import json


class CrashLogService:
    def __init__(self, path="crash.json", enabled=True):
        self.path = path
        self.enabled = enabled

    def write(self, event, **fields):
        if not self.enabled:
            return
        entry = {"event": event, "ts": time.time()}
        entry.update(fields)
        try:
            with open(self.path, "w") as crash_file:
                json.dump(entry, crash_file)
        except Exception as e:
            print("Failed to persist crash log:", e)

    def read(self):
        try:
            with open(self.path, "r") as crash_file:
                return json.load(crash_file)
        except Exception:
            return None

    def clear(self):
        try:
            os.remove(self.path)
        except Exception:
            pass
