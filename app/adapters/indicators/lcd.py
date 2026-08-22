import machine

from app.adapters.base import BaseAdapter
from app.libs import lcd_i2c


class LCDAdapter(BaseAdapter):
    def __init__(
        self,
        sda_pin=22,
        scl_pin=21,
        i2c_addr=0x3E,
        rgb_addr=0x62,
        cols=16,
        rows=2,
        i2c_id=0,
        default_lines=None,
    ):
        self.sda_pin = sda_pin
        self.scl_pin = scl_pin
        self.i2c_addr = i2c_addr
        self.rgb_addr = rgb_addr
        self.cols = cols
        self.rows = rows
        self.i2c_id = i2c_id
        self.default_lines = default_lines
        self._i2c = None
        self._display = None
        self._backlight = None
        self._on = False

    def setup(self):
        try:
            self._i2c = machine.I2C(
                self.i2c_id,
                scl=machine.Pin(self.scl_pin),
                sda=machine.Pin(self.sda_pin),
            )
            self._display = lcd_i2c.LcdI2c(
                self._i2c, addr=self.i2c_addr, cols=self.cols, rows=self.rows
            )
            self._backlight = lcd_i2c.GroveRgbBacklight(self._i2c, addr=self.rgb_addr)
            self._available = True
            self.on()
            if self.default_lines:
                self.show_text(self.default_lines)
        except Exception as e:
            print("Failed to setup LCD display:", e)
            self._i2c = None
            self._display = None
            self._backlight = None
            self._available = False

    def on(self):
        if not self._available:
            return
        self._backlight.on()
        self._on = True

    def off(self):
        if not self._available:
            return
        self._backlight.off()
        self._on = False

    def toggle(self):
        if not self._available:
            return
        self.off() if self._on else self.on()

    def is_on(self):
        return self._on

    def show_text(self, lines):
        if not self._available:
            return
        if isinstance(lines, str):
            lines = [lines]
        self._display.clear()
        for index, line in enumerate(lines):
            self._display.move_to(0, index)
            self._display.putstr(str(line))

    def clear(self):
        if not self._available:
            return
        self._display.clear()

    def deinit(self):
        self._i2c = None
        self._display = None
        self._backlight = None
        self._available = False
        self._on = False
