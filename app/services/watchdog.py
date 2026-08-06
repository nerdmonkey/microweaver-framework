from machine import WDT


class WatchdogService:
    def __init__(self, timeout_ms=8000):
        self.timeout_ms = timeout_ms
        self.wdt = None

    def start(self):
        if self.wdt is None:
            self.wdt = WDT(timeout=self.timeout_ms)
            print("Watchdog started with timeout", self.timeout_ms, "ms")
        return self.wdt

    def feed(self):
        if self.wdt:
            self.wdt.feed()
