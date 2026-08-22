import machine

from app.adapters.base import BaseAdapter


class AutoCyclingRgbAdapter(BaseAdapter):
    """A self-cycling RGB LED: an onboard IC free-runs the color cycle on its
    own once powered -- no data line, no per-channel PWM, no way to control
    color or brightness in software. Only a single GPIO gates power to the
    LED (on()/off()); the "color" it happens to be showing at any moment is
    whatever point the IC's own cycle is at, not something this adapter can
    influence."""

    def __init__(self, pin=25):
        self.pin = pin
        self._enable = None
        self._on = False

    def setup(self):
        try:
            self._enable = machine.Pin(self.pin, machine.Pin.OUT)
            self._available = True
            self.off()
        except Exception as e:
            print("Failed to setup auto-cycling RGB LED:", e)
            self._enable = None
            self._available = False

    def on(self):
        if not self._available:
            return
        self._enable.value(1)
        self._on = True

    def off(self):
        if not self._available:
            return
        self._enable.value(0)
        self._on = False

    def toggle(self):
        if not self._available:
            return
        self.off() if self._on else self.on()

    def is_on(self):
        return self._on

    def deinit(self):
        self._enable = None
        self._available = False
        self._on = False
