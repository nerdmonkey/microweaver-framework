from app.adapters.actuators.rgb import RGBAdapter


def make_adapter(red_pin=25, green_pin=26, blue_pin=27, on_color=(255, 255, 255)):
    return RGBAdapter(
        red_pin=red_pin, green_pin=green_pin, blue_pin=blue_pin, on_color=on_color
    )


def test_setup_marks_available_and_starts_off(mocker):
    mock_pin_cls = mocker.patch("machine.Pin")
    mock_pwm_cls = mocker.patch("machine.PWM")

    adapter = make_adapter(red_pin=12, green_pin=13, blue_pin=14)
    adapter.setup()

    assert adapter.available is True
    assert mock_pin_cls.call_args_list == [
        mocker.call(12),
        mocker.call(13),
        mocker.call(14),
    ]
    assert mock_pwm_cls.call_count == 3
    assert adapter.is_on() is False
    assert mock_pwm_cls.return_value.duty.call_args_list == [
        mocker.call(0),
        mocker.call(0),
        mocker.call(0),
    ]


def test_setup_marks_unavailable_on_failure(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("machine.PWM", side_effect=OSError("pwm unavailable"))

    adapter = make_adapter()
    adapter.setup()

    assert adapter.available is False
    assert adapter._red is None
    assert adapter._green is None
    assert adapter._blue is None


def test_on_sets_on_color(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("machine.PWM", side_effect=lambda *a, **k: mocker.MagicMock())
    adapter = make_adapter(on_color=(255, 0, 128))
    adapter.setup()
    for pwm in (adapter._red, adapter._green, adapter._blue):
        pwm.duty.reset_mock()

    adapter.on()

    assert adapter.is_on() is True
    assert adapter._red.duty.call_args == mocker.call(1023)
    assert adapter._green.duty.call_args == mocker.call(0)
    assert adapter._blue.duty.call_args == mocker.call(513)


def test_off_sets_zero_duty(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("machine.PWM", side_effect=lambda *a, **k: mocker.MagicMock())
    adapter = make_adapter()
    adapter.setup()
    adapter.on()

    adapter.off()

    assert adapter.is_on() is False
    assert adapter._red.duty.call_args == mocker.call(0)
    assert adapter._green.duty.call_args == mocker.call(0)
    assert adapter._blue.duty.call_args == mocker.call(0)


def test_toggle_switches_state(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("machine.PWM")
    adapter = make_adapter()
    adapter.setup()

    adapter.toggle()
    assert adapter.is_on() is True

    adapter.toggle()
    assert adapter.is_on() is False


def test_on_off_toggle_are_noops_when_unavailable(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("machine.PWM", side_effect=OSError("pwm unavailable"))
    adapter = make_adapter()
    adapter.setup()

    adapter.on()
    assert adapter.is_on() is False

    adapter.toggle()
    assert adapter.is_on() is False

    adapter.off()
    assert adapter.is_on() is False


def test_set_applies_given_color(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("machine.PWM", side_effect=lambda *a, **k: mocker.MagicMock())
    adapter = make_adapter()
    adapter.setup()
    for pwm in (adapter._red, adapter._green, adapter._blue):
        pwm.duty.reset_mock()

    adapter.set(color={"r": 255, "g": 0, "b": 128})

    assert adapter.is_on() is True
    assert adapter._red.duty.call_args == mocker.call(1023)
    assert adapter._green.duty.call_args == mocker.call(0)
    assert adapter._blue.duty.call_args == mocker.call(513)


def test_set_accepts_tuple_color(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("machine.PWM", side_effect=lambda *a, **k: mocker.MagicMock())
    adapter = make_adapter()
    adapter.setup()

    adapter.set(color=(0, 255, 0))

    assert adapter._red.duty.call_args == mocker.call(0)
    assert adapter._green.duty.call_args == mocker.call(1023)
    assert adapter._blue.duty.call_args == mocker.call(0)


def test_set_scales_color_by_brightness(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("machine.PWM", side_effect=lambda *a, **k: mocker.MagicMock())
    adapter = make_adapter()
    adapter.setup()

    adapter.set(color={"r": 255, "g": 255, "b": 255}, brightness=0)

    assert adapter._red.duty.call_args == mocker.call(0)
    assert adapter._green.duty.call_args == mocker.call(0)
    assert adapter._blue.duty.call_args == mocker.call(0)


def test_set_brightness_only_reuses_last_color_without_drifting(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("machine.PWM", side_effect=lambda *a, **k: mocker.MagicMock())
    adapter = make_adapter()
    adapter.setup()

    adapter.set(color={"r": 200, "g": 100, "b": 50})
    adapter.set(brightness=128)
    first_red_call = adapter._red.duty.call_args
    adapter.set(brightness=128)
    second_red_call = adapter._red.duty.call_args

    assert first_red_call == second_red_call


def test_set_is_noop_when_unavailable(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("machine.PWM", side_effect=OSError("pwm unavailable"))
    adapter = make_adapter()
    adapter.setup()

    adapter.set(color={"r": 1, "g": 2, "b": 3})

    assert adapter.is_on() is False


def test_state_returns_off_string_when_off(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("machine.PWM", side_effect=lambda *a, **k: mocker.MagicMock())
    adapter = make_adapter()
    adapter.setup()

    assert adapter.state() == "off"


def test_state_returns_base_color_and_brightness_when_on(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("machine.PWM", side_effect=lambda *a, **k: mocker.MagicMock())
    adapter = make_adapter()
    adapter.setup()

    adapter.set(color={"r": 255, "g": 0, "b": 0}, brightness=128)

    assert adapter.state() == {"color": {"r": 255, "g": 0, "b": 0}, "brightness": 128}


def test_state_reports_base_color_not_brightness_scaled_duty_values(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("machine.PWM", side_effect=lambda *a, **k: mocker.MagicMock())
    adapter = make_adapter()
    adapter.setup()

    adapter.set(color={"r": 200, "g": 100, "b": 50}, brightness=0)

    assert adapter.state() == {"color": {"r": 200, "g": 100, "b": 50}, "brightness": 0}


def test_state_after_off_reverts_to_off_string(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("machine.PWM", side_effect=lambda *a, **k: mocker.MagicMock())
    adapter = make_adapter()
    adapter.setup()
    adapter.set(color={"r": 255, "g": 0, "b": 0}, brightness=128)

    adapter.off()

    assert adapter.state() == "off"


def test_is_on_defaults_to_false():
    adapter = make_adapter()

    assert adapter.is_on() is False


def test_deinit_is_safe_when_setup_never_ran():
    adapter = make_adapter()

    adapter.deinit()

    assert adapter.available is False


def test_deinit_resets_state_after_setup(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("machine.PWM", side_effect=lambda *a, **k: mocker.MagicMock())
    adapter = make_adapter()
    adapter.setup()
    adapter.on()
    red, green, blue = adapter._red, adapter._green, adapter._blue

    adapter.deinit()

    assert adapter.available is False
    assert adapter._red is None
    assert adapter._green is None
    assert adapter._blue is None
    assert adapter.is_on() is False
    red.deinit.assert_called_once_with()
    green.deinit.assert_called_once_with()
    blue.deinit.assert_called_once_with()
