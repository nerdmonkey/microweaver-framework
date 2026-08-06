import esp32

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
    def __init__(self):
        self.reason = None

    def read(self):
        cause = esp32.reset_reason()
        self.reason = self._label(cause)
        print("Reset reason:", self.reason)
        return self.reason

    def _label(self, cause):
        for name, label in REASON_LABELS.items():
            if cause == getattr(esp32, name, object()):
                return label
        return "unknown"
