try:
    import ujson as json
except ImportError:
    import json


class BootLoopGuard:
    def __init__(self, path="boot_state.json", max_attempts=5, enabled=True):
        self.path = path
        self.max_attempts = max_attempts
        self.enabled = enabled
        self.attempts = 0

    def check(self):
        if not self.enabled:
            return False

        self.attempts = self._read() + 1
        self._write(self.attempts)

        if self.attempts > self.max_attempts:
            print(
                "Boot-loop detected:",
                self.attempts,
                "consecutive unconfirmed boots",
            )
            return True

        return False

    def confirm(self):
        if not self.enabled:
            return

        self.attempts = 0
        self._write(0)

    def _read(self):
        try:
            with open(self.path, "r") as state_file:
                return int(json.load(state_file).get("attempts", 0))
        except Exception:
            return 0

    def _write(self, attempts):
        try:
            with open(self.path, "w") as state_file:
                json.dump({"attempts": attempts}, state_file)
        except Exception as e:
            print("Failed to persist boot-loop state:", e)
