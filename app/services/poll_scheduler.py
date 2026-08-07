import time


class PollScheduler:
    """Interval gate for periodic sensor reads.

    Mirrors `HealthCheckService.interval_seconds` (app/services/health.py):
    tracks a last-polled timestamp per registered name so a run loop can
    ask "is it time to read this sensor yet" instead of every adapter
    reinventing its own timing loop. Each name may have its own cadence,
    falling back to the scheduler's default `interval_seconds`.
    """

    def __init__(self, interval_seconds=30):
        self.interval_seconds = interval_seconds
        self._intervals = {}
        self._last_polled = {}

    def register(self, name, interval_seconds=None):
        self._intervals[name] = (
            interval_seconds if interval_seconds is not None else self.interval_seconds
        )

    def is_due(self, name):
        interval = self._intervals.get(name, self.interval_seconds)
        last = self._last_polled.get(name)
        return last is None or time.time() - last >= interval

    def mark_polled(self, name):
        self._last_polled[name] = time.time()

    def poll(self, name, read):
        if not self.is_due(name):
            return None
        value = read()
        self.mark_polled(name)
        return value
