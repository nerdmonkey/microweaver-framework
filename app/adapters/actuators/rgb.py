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
        # Reference color `set(color=...)` last stored, independent of the
        # brightness-scaled value actually written to the PWM channels --
        # keeps repeated brightness-only calls from compounding/drifting.
        self._base_color = on_color
        # Last brightness explicitly requested via set(brightness=...); only
        # set() updates this -- on()/off()/toggle() don't touch it, so a bare
        # on() after a dim reapplies whatever on_color was last computed to.
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

    def set(self, color=None, brightness=None):
        """Live-parameterized command (unified devices/{id}/command contract:
        {"command":"set","color":{"r":...,"g":...,"b":...},"brightness":N}).
        `color` may be an {r,g,b} dict or an (r,g,b) tuple/list; omit to reuse
        the last color. `brightness` (0-255) scales that color's channels."""
        if not self._available:
            return
        if color is not None:
            self._base_color = self._normalize_color(color)
        if brightness is not None:
            self._brightness = max(0, min(_CHANNEL_MAX, int(brightness)))
        red, green, blue = self._base_color
        scale = self._brightness / _CHANNEL_MAX
        red, green, blue = (int(red * scale), int(green * scale), int(blue * scale))
        self.on_color = (red, green, blue)
        self._set_color(self.on_color)
        self._on = True

    def state(self):
        """Rich state for devices/{id}/state -- base color + last brightness,
        not the brightness-scaled duty values. "off" (bare string) when the
        LED is off, matching the simple-actuator convention (e.g. relay)."""
        if not self._on:
            return "off"
        red, green, blue = self._base_color
        return {
            "color": {"r": red, "g": green, "b": blue},
            "brightness": self._brightness,
        }

    def _normalize_color(self, color):
        if isinstance(color, dict):
            return (
                int(color.get("r", 0)),
                int(color.get("g", 0)),
                int(color.get("b", 0)),
            )
        red, green, blue = color
        return int(red), int(green), int(blue)

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
