# Grove - LCD RGB Backlight driver.
#
# Unlike a generic PCF8574 "backpack" (bit-banged 4-bit HD44780 protocol via
# a GPIO expander), the Grove LCD RGB Backlight has its own onboard text
# controller that speaks a direct register-write I2C protocol: command bytes
# go to register 0x80, data bytes to register 0x40. The instruction set
# itself (function set, display on/off, clear, entry mode, DDRAM address)
# is the same HD44780 codes, just delivered as whole bytes instead of
# nibble-pulsed over an expander -- no RS/RW/EN pins, no enable pulse.
#
# The RGB backlight is a *separate* I2C device (PCA9633-compatible LED
# driver) at its own address -- writing text has nothing to do with
# backlight control, hence the split into two small classes below.

import time

_COMMAND_REG = 0x80
_DATA_REG = 0x40

_REG_MODE1 = 0x00
_REG_MODE2 = 0x01
_REG_BLUE = 0x02
_REG_GREEN = 0x03
_REG_RED = 0x04
_REG_LEDOUT = 0x08


class LcdI2c:
    def __init__(self, i2c, addr=0x3E, cols=16, rows=2):
        self.i2c = i2c
        self.addr = addr
        self.cols = cols
        self.rows = rows
        self._row_offsets = (0x00, 0x40, 0x14, 0x54)
        self._init_display()

    def _write_command(self, cmd):
        self.i2c.writeto_mem(self.addr, _COMMAND_REG, bytes([cmd]))

    def _write_data(self, data):
        self.i2c.writeto_mem(self.addr, _DATA_REG, bytes([data]))

    def _init_display(self):
        time.sleep(0.05)
        self._write_command(0x28)  # function set: 2-line, 5x8 dots
        self._write_command(0x0C)  # display on, cursor off, blink off
        self.clear()
        self._write_command(0x06)  # entry mode: increment, no shift

    def clear(self):
        self._write_command(0x01)
        time.sleep(0.002)

    def move_to(self, col, row):
        row = min(row, len(self._row_offsets) - 1)
        self._write_command(0x80 | (self._row_offsets[row] + col))

    def putstr(self, text):
        for char in text:
            self._write_data(ord(char))


class GroveRgbBacklight:
    """PCA9633-compatible RGB LED driver at its own I2C address (separate
    chip from the text controller above). Best-effort: some Grove LCD
    variants/clones don't populate this chip at all, so every I2C call is
    guarded -- a missing/non-responding RGB controller degrades to "no
    backlight control" instead of taking the whole display down."""

    def __init__(self, i2c, addr=0x62):
        self.i2c = i2c
        self.addr = addr
        self._available = False
        try:
            self._write(_REG_MODE1, 0x00)
            self._write(_REG_MODE2, 0x00)
            self._write(_REG_LEDOUT, 0xFF)  # individual PWM control, all channels
            self._available = True
        except Exception:
            self._available = False

    def _write(self, reg, value):
        self.i2c.writeto_mem(self.addr, reg, bytes([value]))

    def set_color(self, r, g, b):
        if not self._available:
            return
        try:
            self._write(_REG_RED, r & 0xFF)
            self._write(_REG_GREEN, g & 0xFF)
            self._write(_REG_BLUE, b & 0xFF)
        except Exception as e:
            print("Failed to set LCD backlight color:", e)

    def on(self):
        self.set_color(0xFF, 0xFF, 0xFF)

    def off(self):
        self.set_color(0x00, 0x00, 0x00)
