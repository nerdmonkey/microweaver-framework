import time

from app.services.logger import LogService


def _parse_version(version):
    parts = []
    for part in str(version).split("."):
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(0)
    return parts


class HealthCheckService:
    def __init__(
        self,
        checks=None,
        interval_seconds=30,
        logger=None,
        app_version="",
        metrics=None,
    ):
        self.checks = dict(checks) if checks else {}
        self.interval_seconds = interval_seconds
        self.status = {}
        self._last_polled = None
        self.logger = logger or LogService()
        self.app_version = app_version
        self.metrics = metrics

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

    def report(self):
        report = {
            "app_version": self.app_version,
            "healthy": self.is_healthy(),
            "checks": self.status,
        }
        if self.metrics:
            report["metrics"] = self.metrics.snapshot()
        return report

    def needs_update(self, candidate_version):
        current = _parse_version(self.app_version)
        candidate = _parse_version(candidate_version)
        length = max(len(current), len(candidate))
        current += [0] * (length - len(current))
        candidate += [0] * (length - len(candidate))
        return candidate > current
