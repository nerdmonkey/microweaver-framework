from app.adapters.indicators.oled import OLEDAdapter


def make_adapter(sda_pin=21, scl_pin=22, i2c_addr=0x3C, width=128, height=64, i2c_id=0):
    return OLEDAdapter(
        sda_pin=sda_pin,
        scl_pin=scl_pin,
        i2c_addr=i2c_addr,
        width=width,
        height=height,
        i2c_id=i2c_id,
    )


def test_setup_marks_available_builds_i2c_and_clears_display(mocker):
    mock_pin_cls = mocker.patch("machine.Pin")
    mock_i2c_cls = mocker.patch("machine.I2C")
    mock_ssd1306_cls = mocker.patch("app.libs.ssd1306.SSD1306_I2C")

    adapter = make_adapter(sda_pin=21, scl_pin=22, i2c_addr=0x3C, width=128, height=64)
    adapter.setup()

    assert adapter.available is True
    mock_pin_cls.assert_any_call(22)
    mock_pin_cls.assert_any_call(21)
    mock_i2c_cls.assert_called_once_with(
        0, scl=mock_pin_cls.return_value, sda=mock_pin_cls.return_value
    )
    mock_ssd1306_cls.assert_called_once_with(
        128, 64, mock_i2c_cls.return_value, addr=0x3C
    )
    display = mock_ssd1306_cls.return_value
    display.fill.assert_called_once_with(0)
    display.show.assert_called_once_with()
    assert adapter.is_on() is True


def test_setup_marks_unavailable_on_i2c_failure(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("machine.I2C", side_effect=OSError("i2c unavailable"))
    mocker.patch("app.libs.ssd1306.SSD1306_I2C")

    adapter = make_adapter()
    adapter.setup()

    assert adapter.available is False
    assert adapter._i2c is None
    assert adapter._display is None


def test_setup_marks_unavailable_on_ssd1306_failure(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("machine.I2C")
    mocker.patch(
        "app.libs.ssd1306.SSD1306_I2C", side_effect=OSError("display unavailable")
    )

    adapter = make_adapter()
    adapter.setup()

    assert adapter.available is False
    assert adapter._i2c is None
    assert adapter._display is None


def test_on_calls_poweron_and_sets_state(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("machine.I2C")
    mock_ssd1306_cls = mocker.patch("app.libs.ssd1306.SSD1306_I2C")
    adapter = make_adapter()
    adapter.setup()

    adapter.on()

    mock_ssd1306_cls.return_value.poweron.assert_called_once_with()
    assert adapter.is_on() is True


def test_off_calls_poweroff_and_sets_state(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("machine.I2C")
    mock_ssd1306_cls = mocker.patch("app.libs.ssd1306.SSD1306_I2C")
    adapter = make_adapter()
    adapter.setup()

    adapter.off()

    mock_ssd1306_cls.return_value.poweroff.assert_called_once_with()
    assert adapter.is_on() is False


def test_toggle_switches_state(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("machine.I2C")
    mocker.patch("app.libs.ssd1306.SSD1306_I2C")
    adapter = make_adapter()
    adapter.setup()

    adapter.toggle()
    assert adapter.is_on() is False

    adapter.toggle()
    assert adapter.is_on() is True


def test_on_off_toggle_are_noops_when_unavailable(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("machine.I2C", side_effect=OSError("i2c unavailable"))
    mocker.patch("app.libs.ssd1306.SSD1306_I2C")
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


def test_show_text_draws_each_line_and_pushes_to_display(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("machine.I2C")
    mock_ssd1306_cls = mocker.patch("app.libs.ssd1306.SSD1306_I2C")
    adapter = make_adapter()
    adapter.setup()
    display = mock_ssd1306_cls.return_value
    display.fill.reset_mock()
    display.text.reset_mock()
    display.show.reset_mock()

    adapter.show_text(["line one", "line two"])

    display.fill.assert_called_once_with(0)
    assert display.text.call_args_list == [
        mocker.call("line one", 0, 0),
        mocker.call("line two", 0, 10),
    ]
    display.show.assert_called_once_with()


def test_show_text_wraps_bare_string_into_single_line(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("machine.I2C")
    mock_ssd1306_cls = mocker.patch("app.libs.ssd1306.SSD1306_I2C")
    adapter = make_adapter()
    adapter.setup()
    display = mock_ssd1306_cls.return_value
    display.text.reset_mock()

    adapter.show_text("hello")

    display.text.assert_called_once_with("hello", 0, 0)


def test_show_text_is_noop_when_unavailable(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("machine.I2C", side_effect=OSError("i2c unavailable"))
    mock_ssd1306_cls = mocker.patch("app.libs.ssd1306.SSD1306_I2C")
    adapter = make_adapter()
    adapter.setup()

    adapter.show_text("hello")

    mock_ssd1306_cls.return_value.text.assert_not_called()


def test_clear_blanks_display_without_text_calls(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("machine.I2C")
    mock_ssd1306_cls = mocker.patch("app.libs.ssd1306.SSD1306_I2C")
    adapter = make_adapter()
    adapter.setup()
    display = mock_ssd1306_cls.return_value
    display.fill.reset_mock()
    display.text.reset_mock()
    display.show.reset_mock()

    adapter.clear()

    display.fill.assert_called_once_with(0)
    display.text.assert_not_called()
    display.show.assert_called_once_with()


def test_clear_is_noop_when_unavailable(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("machine.I2C", side_effect=OSError("i2c unavailable"))
    mock_ssd1306_cls = mocker.patch("app.libs.ssd1306.SSD1306_I2C")
    adapter = make_adapter()
    adapter.setup()

    adapter.clear()

    mock_ssd1306_cls.return_value.fill.assert_not_called()


def test_deinit_is_safe_when_setup_never_ran():
    adapter = make_adapter()

    adapter.deinit()

    assert adapter.available is False


def test_deinit_resets_state_after_setup(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("machine.I2C")
    mocker.patch("app.libs.ssd1306.SSD1306_I2C")
    adapter = make_adapter()
    adapter.setup()

    adapter.deinit()

    assert adapter.available is False
    assert adapter._i2c is None
    assert adapter._display is None
    assert adapter.is_on() is False
