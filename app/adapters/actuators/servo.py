import machine

from app.adapters.base import BaseAdapter

_FREQ_HZ = 50
_MIN_DUTY_US = 500
_MAX_DUTY_US = 2500
_PERIOD_US = 1000000 // _FREQ_HZ


class ServoAdapter(BaseAdapter):
    def __init__(self, pin=13, default_angle=90, min_angle=0, max_angle=180):
        self.pin = pin
        self.default_angle = default_angle
        self.min_angle = min_angle
        self.max_angle = max_angle
        self._pwm = None
        self._angle = None
        self._on = False

    def setup(self):
        try:
            self._pwm = machine.PWM(machine.Pin(self.pin), freq=_FREQ_HZ)
            self._available = True
            self.off()
        except Exception as e:
            print("Failed to setup servo:", e)
            self._pwm = None
            self._available = False

    def set_angle(self, angle):
        if not self._available:
            return
        angle = max(self.min_angle, min(self.max_angle, angle))
        duty_us = _MIN_DUTY_US + (
            (angle - self.min_angle)
            * (_MAX_DUTY_US - _MIN_DUTY_US)
            // max(1, self.max_angle - self.min_angle)
        )
        self._pwm.duty_u16(int(duty_us * 65535 / _PERIOD_US))
        self._angle = angle
        self._on = True

    def angle(self):
        return self._angle

    def on(self):
        self.set_angle(self.default_angle)

    def off(self):
        if not self._available:
            return
        self._pwm.duty_u16(0)
        self._angle = None
        self._on = False

    def toggle(self):
        if not self._available:
            return
        self.off() if self._on else self.on()

    def is_on(self):
        return self._on

    def deinit(self):
        if self._pwm is not None:
            try:
                self._pwm.deinit()
            except Exception as e:
                print("Failed to deinit servo:", e)
        self._pwm = None
        self._available = False
        self._angle = None
        self._on = False
