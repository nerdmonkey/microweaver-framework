import machine

from app.adapters.base import BaseAdapter


class FanAdapter(BaseAdapter):
    """Two-pin H-bridge half (in1/in2) DC motor driver -- distinct from a
    single-relay on/off load. in1=1,in2=0 spins one way (cw), in1=0,in2=1
    spins the other (ccw), 0/0 stops. on()/off()/toggle()/is_on() stay as
    a cw-vs-stopped view for callers that only care about "is it running",
    matching every other actuator adapter's contract."""

    def __init__(self, in1_pin=2, in2_pin=4):
        self.in1_pin = in1_pin
        self.in2_pin = in2_pin
        self._in1 = None
        self._in2 = None
        self._on = False
        self._direction = "stop"

    def setup(self):
        try:
            self._in1 = machine.Pin(self.in1_pin, machine.Pin.OUT)
            self._in2 = machine.Pin(self.in2_pin, machine.Pin.OUT)
            self._available = True
            self.stop()
        except Exception as e:
            print("Failed to setup fan:", e)
            self._in1 = None
            self._in2 = None
            self._available = False

    def cw(self):
        if not self._available:
            return
        self._in1.value(1)
        self._in2.value(0)
        self._on = True
        self._direction = "cw"

    def ccw(self):
        if not self._available:
            return
        self._in1.value(0)
        self._in2.value(1)
        self._on = True
        self._direction = "ccw"

    def stop(self):
        if not self._available:
            return
        self._in1.value(0)
        self._in2.value(0)
        self._on = False
        self._direction = "stop"

    def on(self):
        self.cw()

    def off(self):
        self.stop()

    def toggle(self):
        if not self._available:
            return
        self.off() if self._on else self.on()

    def is_on(self):
        return self._on

    def direction(self):
        return self._direction

    def deinit(self):
        self._in1 = None
        self._in2 = None
        self._available = False
        self._on = False
        self._direction = "stop"
