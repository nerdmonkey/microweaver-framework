import machine

from app.adapters.base import BaseAdapter

_DUTY_MAX = 1023
_CHANNEL_MAX = 255


class RGBAdapter(BaseAdapter):
    def __init__(self, red_pin=25, green_pin=26, blue_pin=27, on_color=(255, 255, 255)):
        self.red_pin = red_pin
        self.green_pin = green_pin
        self.blue_pin = blue_pin
        self.on_color = on_color
        self._red = None
        self._green = None
        self._blue = None
        self._on = False

    def setup(self):
        try:
            self._red = machine.PWM(machine.Pin(self.red_pin), freq=1000, duty=0)
            self._green = machine.PWM(machine.Pin(self.green_pin), freq=1000, duty=0)
            self._blue = machine.PWM(machine.Pin(self.blue_pin), freq=1000, duty=0)
            self._available = True
            self.off()
        except Exception as e:
            print("Failed to setup RGB LED:", e)
            self._red = None
            self._green = None
            self._blue = None
            self._available = False

    def _set_color(self, color):
        red, green, blue = color
        self._red.duty(self._to_duty(red))
        self._green.duty(self._to_duty(green))
        self._blue.duty(self._to_duty(blue))

    def _to_duty(self, channel_value):
        return int(channel_value * _DUTY_MAX / _CHANNEL_MAX)

    def on(self):
        if not self._available:
            return
        self._set_color(self.on_color)
        self._on = True

    def off(self):
        if not self._available:
            return
        self._set_color((0, 0, 0))
        self._on = False

    def toggle(self):
        if not self._available:
            return
        self.off() if self._on else self.on()

    def is_on(self):
        return self._on

    def deinit(self):
        for pwm in (self._red, self._green, self._blue):
            if pwm:
                pwm.deinit()
        self._red = None
        self._green = None
        self._blue = None
        self._available = False
        self._on = False
