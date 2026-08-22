import time

import machine

from app.adapters.base import BaseAdapter


class PIRAdapter(BaseAdapter):
    def __init__(self, pin=34, warmup_seconds=10):
        self.pin = pin
        self.warmup_seconds = warmup_seconds
        self._sensor = None
        self._ready_at = None

    def setup(self):
        try:
            self._sensor = machine.Pin(self.pin, machine.Pin.IN)
            self._ready_at = time.time() + self.warmup_seconds
            self._available = True
        except Exception as e:
            print("Failed to setup PIR sensor:", e)
            self._sensor = None
            self._available = False

    def read(self):
        if not self._available:
            return None
        if time.time() < self._ready_at:
            return None
        try:
            return bool(self._sensor.value())
        except Exception as e:
            print("Failed to read PIR sensor:", e)
            return None

    def deinit(self):
        self._sensor = None
        self._ready_at = None
        self._available = False
