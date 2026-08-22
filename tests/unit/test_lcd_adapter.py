from app.adapters.indicators.lcd import LCDAdapter


def make_adapter(
    sda_pin=22, scl_pin=21, i2c_addr=0x3E, rgb_addr=0x62, cols=16, rows=2, i2c_id=0, default_lines=None
):
    return LCDAdapter(
        sda_pin=sda_pin,
        scl_pin=scl_pin,
        i2c_addr=i2c_addr,
        rgb_addr=rgb_addr,
        cols=cols,
        rows=rows,
        i2c_id=i2c_id,
        default_lines=default_lines,
    )


def test_setup_marks_available_builds_i2c_and_turns_backlight_on(mocker):
    mock_pin_cls = mocker.patch("machine.Pin")
    mock_i2c_cls = mocker.patch("machine.I2C")
    mock_lcd_cls = mocker.patch("app.libs.lcd_i2c.LcdI2c")
    mock_backlight_cls = mocker.patch("app.libs.lcd_i2c.GroveRgbBacklight")

    adapter = make_adapter(sda_pin=22, scl_pin=21, i2c_addr=0x3E, rgb_addr=0x62, cols=16, rows=2)
    adapter.setup()

    assert adapter.available is True
    mock_pin_cls.assert_any_call(21)
    mock_pin_cls.assert_any_call(22)
    mock_i2c_cls.assert_called_once_with(
        0, scl=mock_pin_cls.return_value, sda=mock_pin_cls.return_value
    )
    mock_lcd_cls.assert_called_once_with(
        mock_i2c_cls.return_value, addr=0x3E, cols=16, rows=2
    )
    mock_backlight_cls.assert_called_once_with(mock_i2c_cls.return_value, addr=0x62)
    mock_backlight_cls.return_value.on.assert_called_once_with()
    assert adapter.is_on() is True


def test_setup_marks_unavailable_on_i2c_failure(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("machine.I2C", side_effect=OSError("i2c unavailable"))
    mocker.patch("app.libs.lcd_i2c.LcdI2c")
    mocker.patch("app.libs.lcd_i2c.GroveRgbBacklight")

    adapter = make_adapter()
    adapter.setup()

    assert adapter.available is False
    assert adapter._i2c is None
    assert adapter._display is None
    assert adapter._backlight is None


def test_setup_marks_unavailable_on_lcd_init_failure(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("machine.I2C")
    mocker.patch("app.libs.lcd_i2c.LcdI2c", side_effect=OSError("lcd unavailable"))
    mocker.patch("app.libs.lcd_i2c.GroveRgbBacklight")

    adapter = make_adapter()
    adapter.setup()

    assert adapter.available is False
    assert adapter._i2c is None
    assert adapter._display is None
    assert adapter._backlight is None


def test_on_turns_backlight_on_and_sets_state(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("machine.I2C")
    mocker.patch("app.libs.lcd_i2c.LcdI2c")
    mock_backlight_cls = mocker.patch("app.libs.lcd_i2c.GroveRgbBacklight")
    adapter = make_adapter()
    adapter.setup()
    mock_backlight_cls.return_value.on.reset_mock()

    adapter.on()

    mock_backlight_cls.return_value.on.assert_called_once_with()
    assert adapter.is_on() is True


def test_off_turns_backlight_off_and_sets_state(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("machine.I2C")
    mocker.patch("app.libs.lcd_i2c.LcdI2c")
    mock_backlight_cls = mocker.patch("app.libs.lcd_i2c.GroveRgbBacklight")
    adapter = make_adapter()
    adapter.setup()

    adapter.off()

    mock_backlight_cls.return_value.off.assert_called_once_with()
    assert adapter.is_on() is False


def test_toggle_switches_state(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("machine.I2C")
    mocker.patch("app.libs.lcd_i2c.LcdI2c")
    mocker.patch("app.libs.lcd_i2c.GroveRgbBacklight")
    adapter = make_adapter()
    adapter.setup()

    adapter.toggle()
    assert adapter.is_on() is False

    adapter.toggle()
    assert adapter.is_on() is True


def test_on_off_toggle_are_noops_when_unavailable(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("machine.I2C", side_effect=OSError("i2c unavailable"))
    mocker.patch("app.libs.lcd_i2c.LcdI2c")
    mocker.patch("app.libs.lcd_i2c.GroveRgbBacklight")
    adapter = make_adapter()
    adapter.setup()

    adapter.on()
    assert adapter.is_on() is False

    adapter.toggle()
    assert adapter.is_on() is False

    adapter.off()
    assert adapter.is_on() is False


def test_is_on_defaults_to_false():
    adapter = make_adapter()

    assert adapter.is_on() is False


def test_setup_shows_default_lines_when_configured(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("machine.I2C")
    mock_lcd_cls = mocker.patch("app.libs.lcd_i2c.LcdI2c")
    mocker.patch("app.libs.lcd_i2c.GroveRgbBacklight")
    adapter = make_adapter(default_lines=["Agnes Smart Home", "dev_fa6648eb"])

    adapter.setup()

    display = mock_lcd_cls.return_value
    assert display.move_to.call_args_list == [mocker.call(0, 0), mocker.call(0, 1)]
    assert display.putstr.call_args_list == [
        mocker.call("Agnes Smart Home"),
        mocker.call("dev_fa6648eb"),
    ]


def test_setup_skips_default_lines_when_not_configured(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("machine.I2C")
    mock_lcd_cls = mocker.patch("app.libs.lcd_i2c.LcdI2c")
    mocker.patch("app.libs.lcd_i2c.GroveRgbBacklight")
    adapter = make_adapter(default_lines=None)

    adapter.setup()

    mock_lcd_cls.return_value.putstr.assert_not_called()


def test_show_text_draws_each_line_and_pushes_to_display(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("machine.I2C")
    mock_lcd_cls = mocker.patch("app.libs.lcd_i2c.LcdI2c")
    mocker.patch("app.libs.lcd_i2c.GroveRgbBacklight")
    adapter = make_adapter()
    adapter.setup()
    display = mock_lcd_cls.return_value
    display.clear.reset_mock()
    display.move_to.reset_mock()
    display.putstr.reset_mock()

    adapter.show_text(["line one", "line two"])

    display.clear.assert_called_once_with()
    assert display.move_to.call_args_list == [
        mocker.call(0, 0),
        mocker.call(0, 1),
    ]
    assert display.putstr.call_args_list == [
        mocker.call("line one"),
        mocker.call("line two"),
    ]


def test_show_text_wraps_bare_string_into_single_line(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("machine.I2C")
    mock_lcd_cls = mocker.patch("app.libs.lcd_i2c.LcdI2c")
    mocker.patch("app.libs.lcd_i2c.GroveRgbBacklight")
    adapter = make_adapter()
    adapter.setup()
    display = mock_lcd_cls.return_value
    display.putstr.reset_mock()

    adapter.show_text("hello")

    display.putstr.assert_called_once_with("hello")


def test_show_text_is_noop_when_unavailable(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("machine.I2C", side_effect=OSError("i2c unavailable"))
    mock_lcd_cls = mocker.patch("app.libs.lcd_i2c.LcdI2c")
    mocker.patch("app.libs.lcd_i2c.GroveRgbBacklight")
    adapter = make_adapter()
    adapter.setup()

    adapter.show_text("hello")

    mock_lcd_cls.return_value.putstr.assert_not_called()


def test_clear_blanks_display(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("machine.I2C")
    mock_lcd_cls = mocker.patch("app.libs.lcd_i2c.LcdI2c")
    mocker.patch("app.libs.lcd_i2c.GroveRgbBacklight")
    adapter = make_adapter()
    adapter.setup()
    display = mock_lcd_cls.return_value
    display.clear.reset_mock()

    adapter.clear()

    display.clear.assert_called_once_with()


def test_clear_is_noop_when_unavailable(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("machine.I2C", side_effect=OSError("i2c unavailable"))
    mock_lcd_cls = mocker.patch("app.libs.lcd_i2c.LcdI2c")
    mocker.patch("app.libs.lcd_i2c.GroveRgbBacklight")
    adapter = make_adapter()
    adapter.setup()

    adapter.clear()

    mock_lcd_cls.return_value.clear.assert_not_called()


def test_deinit_is_safe_when_setup_never_ran():
    adapter = make_adapter()

    adapter.deinit()

    assert adapter.available is False


def test_deinit_resets_state_after_setup(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("machine.I2C")
    mocker.patch("app.libs.lcd_i2c.LcdI2c")
    mocker.patch("app.libs.lcd_i2c.GroveRgbBacklight")
    adapter = make_adapter()
    adapter.setup()

    adapter.deinit()

    assert adapter.available is False
    assert adapter._i2c is None
    assert adapter._display is None
    assert adapter._backlight is None
    assert adapter.is_on() is False
