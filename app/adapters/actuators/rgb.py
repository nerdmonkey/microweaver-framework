import machine

from app.adapters.base import BaseAdapter

_DUTY_MAX = 1023
_CHANNEL_MAX = 255


class RGBAdapter(BaseAdapter):
    def __init__(self, red_pin=25, green_pin=26, blue_pin=27, on_color=(255, 255, 255)):
        self.red_pin = red_pin
        self.green_pin = green_pin
        self.blue_pin = blue_pin
        self._color = tuple(on_color)
        self._brightness = _CHANNEL_MAX
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

    def _apply(self):
        scale = self._brightness / _CHANNEL_MAX
        red, green, blue = self._color
        self._red.duty(self._to_duty(red * scale))
        self._green.duty(self._to_duty(green * scale))
        self._blue.duty(self._to_duty(blue * scale))

    def _to_duty(self, channel_value):
        clamped = max(0, min(_CHANNEL_MAX, int(channel_value)))
        return int(clamped * _DUTY_MAX / _CHANNEL_MAX)

    def on(self):
        if not self._available:
            return
        self._on = True
        self._apply()

    def off(self):
        if not self._available:
            return
        self._red.duty(0)
        self._green.duty(0)
        self._blue.duty(0)
        self._on = False

    def toggle(self):
        if not self._available:
            return
        self.off() if self._on else self.on()

    def is_on(self):
        return self._on

    def set(self, color=None, brightness=None):
        """Structured unified command: {"command":"set", "color":{"r","g","b"},
        "brightness": 0-255}. Either param alone is valid -- change just the
        color (keep brightness) or just the brightness (keep color)."""
        if not self._available:
            return
        if color is not None:
            if isinstance(color, dict):
                self._color = (
                    int(color.get("r", 0)),
                    int(color.get("g", 0)),
                    int(color.get("b", 0)),
                )
            else:
                red, green, blue = color
                self._color = (int(red), int(green), int(blue))
        if brightness is not None:
            self._brightness = max(0, min(_CHANNEL_MAX, int(brightness)))
        self._on = True
        self._apply()

    def state(self):
        if not self._on:
            return "off"
        red, green, blue = self._color
        return {"color": {"r": red, "g": green, "b": blue}, "brightness": self._brightness}

    def deinit(self):
        for pwm in (self._red, self._green, self._blue):
            if pwm:
                pwm.deinit()
        self._red = None
        self._green = None
        self._blue = None
        self._available = False
        self._on = False
