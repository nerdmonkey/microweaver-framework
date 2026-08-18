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
