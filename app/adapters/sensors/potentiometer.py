import machine

from app.adapters.base import BaseAdapter


class PotentiometerAdapter(BaseAdapter):
    def __init__(self, pin=34, min_reading=0, max_reading=65535):
        self.pin = pin
        self.min_reading = min_reading
        self.max_reading = max_reading
        self._adc = None

    def setup(self):
        try:
            self._adc = machine.ADC(machine.Pin(self.pin))
            self._adc.atten(machine.ADC.ATTN_11DB)
            self._available = True
        except Exception as e:
            print("Failed to setup potentiometer:", e)
            self._adc = None
            self._available = False

    def read(self):
        if not self._available:
            return None
        try:
            raw = self._adc.read_u16()
        except Exception as e:
            print("Failed to read potentiometer:", e)
            return None
        span = self.max_reading - self.min_reading
        if span <= 0:
            return 0.0
        percent = (raw - self.min_reading) / span * 100
        return round(max(0.0, min(100.0, percent)), 1)

    def deinit(self):
        self._adc = None
        self._available = False
