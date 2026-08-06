import time

from app.services.logger import LogService


class HealthCheckService:
    def __init__(self, checks=None, interval_seconds=30, logger=None):
        self.checks = dict(checks) if checks else {}
        self.interval_seconds = interval_seconds
        self.status = {}
        self._last_polled = None
        self.logger = logger or LogService()

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
                healthy = bool(check())
                self.status[name] = {
                    "healthy": healthy,
                    "error": None,
                    "checked_at": now,
                }
                if not healthy:
                    self.logger.log(
                        "health_check_failed",
                        level="warning",
                        service=name,
                        error=None,
                    )
            except Exception as e:
                self.status[name] = {
                    "healthy": False,
                    "error": str(e),
                    "checked_at": now,
                }
                self.logger.log(
                    "health_check_failed",
                    level="warning",
                    service=name,
                    error=str(e),
                )

        self._last_polled = now
        return self.status

    def is_healthy(self):
        return all(entry["healthy"] for entry in self.status.values())
