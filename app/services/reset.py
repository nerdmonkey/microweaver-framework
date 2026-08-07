import esp32

from app.services.logger import LogService

REASON_LABELS = {
    "POWERON_RESET": "power_on",
    "SW_RESET": "software",
    "OWDT_RESET": "watchdog",
    "DEEPSLEEP_RESET": "deep_sleep",
    "SDIO_RESET": "sdio",
    "TG0WDT_SYS_RESET": "watchdog",
    "TG1WDT_SYS_RESET": "watchdog",
    "RTCWDT_SYS_RESET": "watchdog",
    "INTRUSION_RESET": "intrusion",
    "TGWDT_CPU_RESET": "watchdog",
    "SW_CPU_RESET": "software",
    "RTCWDT_CPU_RESET": "watchdog",
    "EXT_CPU_RESET": "external",
    "RTCWDT_BROWN_OUT_RESET": "brownout",
    "RTCWDT_RTC_RESET": "watchdog",
}


class ResetService:
    def __init__(self, logger=None, crash_log=None):
        self.reason = None
        self.logger = logger or LogService()
        self.crash_log = crash_log

    def read(self):
        reset_reason = getattr(esp32, "reset_reason", None)
        if reset_reason is None:
            self.reason = "unknown"
        else:
            self.reason = self._label(reset_reason())
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
            if cause == getattr(esp32, name, object()):
                return label
        return "unknown"
