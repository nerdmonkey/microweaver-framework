import dht
import machine

from app.adapters.base import BaseAdapter


class DHT22Adapter(BaseAdapter):
    # AOSong DHT22 datasheet: collecting period must be >= 2s; polling
    # faster than this returns stale/garbage readings instead of erroring.
    read_interval_seconds = 2

    def __init__(self, pin=4):
        self.pin = pin
        self._sensor = None
        self._temperature = None
        self._humidity = None

    def setup(self):
        try:
            self._sensor = dht.DHT22(machine.Pin(self.pin))
            self._available = True
        except Exception as e:
            print("Failed to setup DHT22 sensor:", e)
            self._sensor = None
            self._available = False

    def read(self):
        if not self._available:
            return None
        try:
            self._sensor.measure()
            self._temperature = self._sensor.temperature()
            self._humidity = self._sensor.humidity()
            return self._temperature, self._humidity
        except Exception as e:
            print("Failed to read DHT22 sensor:", e)
            return None

    def temperature(self):
        return self._temperature

    def humidity(self):
        return self._humidity

    def deinit(self):
        self._sensor = None
        self._available = False
