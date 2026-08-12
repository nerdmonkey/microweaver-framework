import machine

from app.adapters.base import BaseAdapter
from app.libs import ssd1306


class OLEDAdapter(BaseAdapter):
    def __init__(
        self,
        sda_pin=21,
        scl_pin=22,
        i2c_addr=0x3C,
        width=128,
        height=64,
        i2c_id=0,
    ):
        self.sda_pin = sda_pin
        self.scl_pin = scl_pin
        self.i2c_addr = i2c_addr
        self.width = width
        self.height = height
        self.i2c_id = i2c_id
        self._i2c = None
        self._display = None
        self._on = False

    def setup(self):
        try:
            self._i2c = machine.I2C(
                self.i2c_id,
                scl=machine.Pin(self.scl_pin),
                sda=machine.Pin(self.sda_pin),
            )
            self._display = ssd1306.SSD1306_I2C(
                self.width, self.height, self._i2c, addr=self.i2c_addr
            )
            self._available = True
            self.clear()
            self._on = True
        except Exception as e:
            print("Failed to setup OLED display:", e)
            self._i2c = None
            self._display = None
            self._available = False

    def on(self):
        if not self._available:
            return
        self._display.poweron()
        self._on = True

    def off(self):
        if not self._available:
            return
        self._display.poweroff()
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
        self._display.fill(0)
        for index, line in enumerate(lines):
            self._display.text(str(line), 0, index * 10)
        self._display.show()

    def clear(self):
        self.show_text([])

    def deinit(self):
        self._i2c = None
        self._display = None
        self._available = False
        self._on = False
