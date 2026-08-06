import machine

from app.adapters.base import BaseAdapter


class RelayAdapter(BaseAdapter):
    def __init__(self, pin=5, active_high=True):
        self.pin = pin
        self.active_high = active_high
        self._relay = None
        self._on = False

    def setup(self):
        try:
            self._relay = machine.Pin(self.pin, machine.Pin.OUT)
            self._available = True
            self.off()
        except Exception as e:
            print("Failed to setup relay:", e)
            self._relay = None
            self._available = False

    def on(self):
        if not self._available:
            return
        self._relay.value(1 if self.active_high else 0)
        self._on = True

    def off(self):
        if not self._available:
            return
        self._relay.value(0 if self.active_high else 1)
        self._on = False

    def toggle(self):
        if not self._available:
            return
        self.off() if self._on else self.on()

    def is_on(self):
        return self._on

    def deinit(self):
        self._relay = None
        self._available = False
        self._on = False
