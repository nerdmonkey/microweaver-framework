import time

import machine

from app.adapters.base import BaseAdapter


class StatusLEDAdapter(BaseAdapter):
    def __init__(self, pin=2, active_high=True, freq=1000):
        self.pin = pin
        self.active_high = active_high
        self.freq = freq
        self._led = None
        self._on = False
        self._brightness = 0

    def setup(self):
        try:
            self._led = machine.PWM(machine.Pin(self.pin), freq=self.freq)
            self._available = True
            self.off()
        except Exception as e:
            print("Failed to setup status LED:", e)
            self._led = None
            self._available = False

    def on(self):
        self.set_brightness(100)

    def off(self):
        self.set_brightness(0)

    def toggle(self):
        self.off() if self._on else self.on()

    def set_brightness(self, percent):
        if not self._available:
            return
        percent = max(0, min(100, percent))
        duty = round(percent / 100 * 65535)
        if not self.active_high:
            duty = 65535 - duty
        self._led.duty_u16(duty)
        self._brightness = percent
        self._on = percent > 0

    def brightness(self):
        return self._brightness

    def is_on(self):
        return self._on

    def blink(self, times, on_seconds=0.2, off_seconds=0.2):
        if not self._available:
            return
        for _ in range(times):
            self.on()
            time.sleep(on_seconds)
            self.off()
            time.sleep(off_seconds)

    def deinit(self):
        if self._led is not None:
            try:
                self._led.deinit()
            except Exception as e:
                print("Failed to deinit status LED:", e)
        self._led = None
        self._available = False
        self._on = False
        self._brightness = 0
