import machine

from app.services.logger import LogService

REASON_LABELS = {
    "PWRON_RESET": "power_on",
    "HARD_RESET": "hard_reset",
    "WDT_RESET": "watchdog",
    "DEEPSLEEP_RESET": "deep_sleep",
    "SOFT_RESET": "software",
}


class ResetService:
    def __init__(self, logger=None, crash_log=None):
        self.reason = None
        self.logger = logger or LogService()
        self.crash_log = crash_log

    def read(self):
        reset_cause = getattr(machine, "reset_cause", None)
        if reset_cause is None:
            self.reason = "unknown"
        else:
            self.reason = self._label(reset_cause())
        if self.reason == "watchdog":
            self.logger.log("watchdog_trip", level="warning", reason=self.reason)
        else:
            self.logger.log("reset", reason=self.reason)
        self._recover_crash_log()
        return self.reason

    def _recover_crash_log(self):
        if not self.crash_log:
            return
        entry = self.crash_log.read()
        if not entry:
            return
        fields = dict(entry)
        fields["original_event"] = fields.pop("event", "unknown")
        self.logger.log("crash_log_recovered", level="error", **fields)
        self.crash_log.clear()

    def _label(self, cause):
        for name, label in REASON_LABELS.items():
            if cause == getattr(machine, name, object()):
                return label
        return "unknown"
