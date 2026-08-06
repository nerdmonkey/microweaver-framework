import time


class HealthCheckService:
    def __init__(self, checks=None, interval_seconds=30):
        self.checks = dict(checks) if checks else {}
        self.interval_seconds = interval_seconds
        self.status = {}
        self._last_polled = None

    def register(self, name, check):
        self.checks[name] = check

    def poll(self):
        now = time.time()
        if (
            self._last_polled is not None
            and now - self._last_polled < self.interval_seconds
        ):
            return self.status

        for name, check in self.checks.items():
            try:
                self.status[name] = {
                    "healthy": bool(check()),
                    "error": None,
                    "checked_at": now,
                }
            except Exception as e:
                self.status[name] = {
                    "healthy": False,
                    "error": str(e),
                    "checked_at": now,
                }

        self._last_polled = now
        return self.status

    def is_healthy(self):
        return all(entry["healthy"] for entry in self.status.values())
