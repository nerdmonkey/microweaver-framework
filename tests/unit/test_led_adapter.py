from app.adapters.indicators.led import StatusLEDAdapter


def make_adapter(pin=2, active_high=True, freq=1000):
    return StatusLEDAdapter(pin=pin, active_high=active_high, freq=freq)


def test_setup_marks_available_and_starts_off(mocker):
    mock_pin_cls = mocker.patch("machine.Pin")
    mock_pwm_cls = mocker.patch("machine.PWM")

    adapter = make_adapter(pin=4, freq=500)
    adapter.setup()

    assert adapter.available is True
    mock_pin_cls.assert_called_once_with(4)
    mock_pwm_cls.assert_called_once_with(mock_pin_cls.return_value, freq=500)
    mock_pwm_cls.return_value.duty_u16.assert_called_once_with(0)
    assert adapter.is_on() is False
    assert adapter.brightness() == 0


def test_setup_marks_unavailable_on_failure(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("machine.PWM", side_effect=OSError("pwm unavailable"))

    adapter = make_adapter()
    adapter.setup()

    assert adapter.available is False
    assert adapter._led is None


def test_on_sets_full_duty_active_high(mocker):
    mocker.patch("machine.Pin")
    mock_pwm_cls = mocker.patch("machine.PWM")
    adapter = make_adapter(active_high=True)
    adapter.setup()
    mock_pwm_cls.return_value.duty_u16.reset_mock()

    adapter.on()

    mock_pwm_cls.return_value.duty_u16.assert_called_once_with(65535)
    assert adapter.is_on() is True
    assert adapter.brightness() == 100


def test_on_sets_full_duty_active_low(mocker):
    mocker.patch("machine.Pin")
    mock_pwm_cls = mocker.patch("machine.PWM")
    adapter = make_adapter(active_high=False)
    adapter.setup()
    mock_pwm_cls.return_value.duty_u16.reset_mock()

    adapter.on()

    mock_pwm_cls.return_value.duty_u16.assert_called_once_with(0)
    assert adapter.is_on() is True


def test_off_sets_zero_duty_active_high(mocker):
    mocker.patch("machine.Pin")
    mock_pwm_cls = mocker.patch("machine.PWM")
    adapter = make_adapter(active_high=True)
    adapter.setup()
    adapter.on()
    mock_pwm_cls.return_value.duty_u16.reset_mock()

    adapter.off()

    mock_pwm_cls.return_value.duty_u16.assert_called_once_with(0)
    assert adapter.is_on() is False


def test_set_brightness_clamps_and_scales(mocker):
    mocker.patch("machine.Pin")
    mock_pwm_cls = mocker.patch("machine.PWM")
    adapter = make_adapter()
    adapter.setup()
    mock_pwm_cls.return_value.duty_u16.reset_mock()

    adapter.set_brightness(150)
    mock_pwm_cls.return_value.duty_u16.assert_called_once_with(65535)
    assert adapter.brightness() == 100

    mock_pwm_cls.return_value.duty_u16.reset_mock()
    adapter.set_brightness(-10)
    mock_pwm_cls.return_value.duty_u16.assert_called_once_with(0)
    assert adapter.brightness() == 0

    mock_pwm_cls.return_value.duty_u16.reset_mock()
    adapter.set_brightness(50)
    mock_pwm_cls.return_value.duty_u16.assert_called_once_with(32768)
    assert adapter.brightness() == 50
    assert adapter.is_on() is True


def test_toggle_switches_state(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("machine.PWM")
    adapter = make_adapter()
    adapter.setup()

    adapter.toggle()
    assert adapter.is_on() is True

    adapter.toggle()
    assert adapter.is_on() is False


def test_on_off_toggle_set_brightness_are_noops_when_unavailable(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("machine.PWM", side_effect=OSError("pwm unavailable"))
    adapter = make_adapter()
    adapter.setup()

    adapter.on()
    assert adapter.is_on() is False

    adapter.toggle()
    assert adapter.is_on() is False

    adapter.set_brightness(75)
    assert adapter.brightness() == 0

    adapter.off()
    assert adapter.is_on() is False


def test_blink_toggles_on_off_given_times_with_delays(mocker):
    mocker.patch("machine.Pin")
    mock_pwm_cls = mocker.patch("machine.PWM")
    mock_sleep = mocker.patch("time.sleep")
    adapter = make_adapter()
    adapter.setup()
    mock_pwm_cls.return_value.duty_u16.reset_mock()

    adapter.blink(3, on_seconds=0.1, off_seconds=0.05)

    assert (
        mock_pwm_cls.return_value.duty_u16.call_args_list
        == [
            mocker.call(65535),
            mocker.call(0),
        ]
        * 3
    )
    assert mock_sleep.call_args_list == [mocker.call(0.1), mocker.call(0.05)] * 3
    assert adapter.is_on() is False


def test_blink_is_noop_when_unavailable(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("machine.PWM", side_effect=OSError("pwm unavailable"))
    mock_sleep = mocker.patch("time.sleep")
    adapter = make_adapter()
    adapter.setup()

    adapter.blink(3)

    mock_sleep.assert_not_called()


def test_is_on_defaults_to_false():
    adapter = make_adapter()

    assert adapter.is_on() is False


def test_deinit_is_safe_when_setup_never_ran():
    adapter = make_adapter()

    adapter.deinit()

    assert adapter.available is False


def test_deinit_resets_state_after_setup(mocker):
    mocker.patch("machine.Pin")
    mock_pwm_cls = mocker.patch("machine.PWM")
    adapter = make_adapter()
    adapter.setup()
    adapter.on()

    adapter.deinit()

    mock_pwm_cls.return_value.deinit.assert_called_once()
    assert adapter.available is False
    assert adapter._led is None
    assert adapter.is_on() is False
    assert adapter.brightness() == 0


def test_deinit_handles_pwm_deinit_failure(mocker):
    mocker.patch("machine.Pin")
    mock_pwm_cls = mocker.patch("machine.PWM")
    mock_pwm_cls.return_value.deinit.side_effect = OSError("already released")
    adapter = make_adapter()
    adapter.setup()

    adapter.deinit()

    assert adapter.available is False
    assert adapter._led is None


def test_state_returns_off_string_when_off(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("machine.PWM")
    adapter = make_adapter()
    adapter.setup()

    assert adapter.state() == "off"


def test_state_returns_brightness_dict_when_on(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("machine.PWM")
    adapter = make_adapter()
    adapter.setup()

    adapter.set_brightness(42)

    assert adapter.state() == {"brightness": 42}
