from unittest.mock import MagicMock, call

from app.libs.lcd_i2c import GroveRgbBacklight, LcdI2c

_COMMAND_REG = 0x80
_DATA_REG = 0x40


def make_lcd(addr=0x3E, cols=16, rows=2):
    i2c = MagicMock()
    lcd = LcdI2c(i2c, addr=addr, cols=cols, rows=rows)
    i2c.writeto_mem.reset_mock()
    return lcd, i2c


def test_init_writes_function_set_display_on_and_entry_mode_over_i2c():
    i2c = MagicMock()

    lcd = LcdI2c(i2c, addr=0x3E, cols=16, rows=2)

    assert lcd.addr == 0x3E
    assert call(0x3E, _COMMAND_REG, bytes([0x28])) in i2c.writeto_mem.call_args_list
    assert call(0x3E, _COMMAND_REG, bytes([0x0C])) in i2c.writeto_mem.call_args_list
    assert call(0x3E, _COMMAND_REG, bytes([0x06])) in i2c.writeto_mem.call_args_list


def test_clear_writes_clear_command_to_command_register():
    lcd, i2c = make_lcd()

    lcd.clear()

    i2c.writeto_mem.assert_called_once_with(lcd.addr, _COMMAND_REG, bytes([0x01]))


def test_move_to_within_bounds_targets_row_offset():
    lcd, i2c = make_lcd(rows=2)

    lcd.move_to(3, 1)

    i2c.writeto_mem.assert_called_once_with(lcd.addr, _COMMAND_REG, bytes([0x80 | (0x40 + 3)]))


def test_move_to_clamps_row_beyond_known_offsets():
    lcd, i2c = make_lcd(rows=2)

    lcd.move_to(0, 5)

    # 4 known row offsets (indices 0-3) -- row 5 clamps to index 3
    i2c.writeto_mem.assert_called_once_with(lcd.addr, _COMMAND_REG, bytes([0x80 | 0x54]))


def test_putstr_writes_one_data_byte_per_character():
    lcd, i2c = make_lcd()

    lcd.putstr("hi")

    assert i2c.writeto_mem.call_args_list == [
        call(lcd.addr, _DATA_REG, bytes([ord("h")])),
        call(lcd.addr, _DATA_REG, bytes([ord("i")])),
    ]


# --------------------------------------------------------------------------
# GroveRgbBacklight -- separate PCA9633-compatible RGB LED driver chip
# --------------------------------------------------------------------------


def make_backlight(addr=0x62):
    i2c = MagicMock()
    backlight = GroveRgbBacklight(i2c, addr=addr)
    i2c.writeto_mem.reset_mock()
    return backlight, i2c


def test_backlight_init_configures_mode_and_ledout_registers():
    i2c = MagicMock()

    backlight = GroveRgbBacklight(i2c, addr=0x62)

    assert backlight._available is True
    assert call(0x62, 0x00, bytes([0x00])) in i2c.writeto_mem.call_args_list  # MODE1
    assert call(0x62, 0x01, bytes([0x00])) in i2c.writeto_mem.call_args_list  # MODE2
    assert call(0x62, 0x08, bytes([0xFF])) in i2c.writeto_mem.call_args_list  # LEDOUT


def test_backlight_marks_unavailable_when_chip_does_not_respond():
    i2c = MagicMock()
    i2c.writeto_mem.side_effect = OSError(19, "ENODEV")

    backlight = GroveRgbBacklight(i2c, addr=0x62)

    assert backlight._available is False


def test_set_color_writes_rgb_registers():
    backlight, i2c = make_backlight()

    backlight.set_color(0x11, 0x22, 0x33)

    assert i2c.writeto_mem.call_args_list == [
        call(0x62, 0x04, bytes([0x11])),  # RED
        call(0x62, 0x03, bytes([0x22])),  # GREEN
        call(0x62, 0x02, bytes([0x33])),  # BLUE
    ]


def test_set_color_noop_when_unavailable():
    i2c = MagicMock()
    i2c.writeto_mem.side_effect = OSError(19, "ENODEV")
    backlight = GroveRgbBacklight(i2c, addr=0x62)
    i2c.writeto_mem.side_effect = None
    i2c.writeto_mem.reset_mock()

    backlight.set_color(0xFF, 0xFF, 0xFF)

    i2c.writeto_mem.assert_not_called()


def test_on_sets_full_white():
    backlight, i2c = make_backlight()

    backlight.on()

    assert i2c.writeto_mem.call_args_list == [
        call(0x62, 0x04, bytes([0xFF])),
        call(0x62, 0x03, bytes([0xFF])),
        call(0x62, 0x02, bytes([0xFF])),
    ]


def test_off_sets_zero():
    backlight, i2c = make_backlight()

    backlight.off()

    assert i2c.writeto_mem.call_args_list == [
        call(0x62, 0x04, bytes([0x00])),
        call(0x62, 0x03, bytes([0x00])),
        call(0x62, 0x02, bytes([0x00])),
    ]


def test_set_color_survives_transient_write_error():
    backlight, i2c = make_backlight()
    i2c.writeto_mem.side_effect = OSError(5, "EIO")

    backlight.set_color(0xFF, 0x00, 0x00)  # should not raise
