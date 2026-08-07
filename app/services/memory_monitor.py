import gc

from machine import reset

from app.services.logger import LogService


class MemoryMonitorService:
    def __init__(
        self, threshold_bytes=10000, action="log", logger=None, crash_log=None
    ):
        self.threshold_bytes = threshold_bytes
        self.action = action
        self.logger = logger or LogService()
        self.crash_log = crash_log

    def free_bytes(self):
        return gc.mem_free()

    def check(self):
        free = self.free_bytes()
        if free >= self.threshold_bytes:
            return False

        level = "warning" if self.action == "warn" else "info"
        self.logger.log(
            "memory_warning",
            level=level,
            free_bytes=free,
            threshold_bytes=self.threshold_bytes,
            action=self.action,
        )

        if self.action == "restart":
            if self.crash_log:
                self.crash_log.write(
                    "memory_restart",
                    free_bytes=free,
                    threshold_bytes=self.threshold_bytes,
                )
            reset()

        return True
