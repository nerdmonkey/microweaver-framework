from app.adapters.actuators.servo import ServoAdapter


def make_adapter(pin=13, default_angle=90, min_angle=0, max_angle=180):
    return ServoAdapter(
        pin=pin, default_angle=default_angle, min_angle=min_angle, max_angle=max_angle
    )


def test_setup_marks_available_and_starts_off(mocker):
    mock_pin_cls = mocker.patch("machine.Pin")
    mock_pwm_cls = mocker.patch("machine.PWM")

    adapter = make_adapter(pin=13)
    adapter.setup()

    assert adapter.available is True
    mock_pin_cls.assert_called_once_with(13)
    mock_pwm_cls.assert_called_once_with(mock_pin_cls.return_value, freq=50)
    mock_pwm_cls.return_value.duty_u16.assert_called_once_with(0)
    assert adapter.is_on() is False


def test_setup_marks_unavailable_on_failure(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("machine.PWM", side_effect=OSError("pwm unavailable"))

    adapter = make_adapter()
    adapter.setup()

    assert adapter.available is False
    assert adapter._pwm is None


def test_set_angle_clamps_to_max_and_marks_on(mocker):
    mocker.patch("machine.Pin")
    mock_pwm_cls = mocker.patch("machine.PWM")
    adapter = make_adapter(min_angle=0, max_angle=180)
    adapter.setup()
    mock_pwm_cls.return_value.duty_u16.reset_mock()

    adapter.set_angle(250)

    assert adapter.angle() == 180
    assert adapter.is_on() is True
    mock_pwm_cls.return_value.duty_u16.assert_called_once()


def test_set_angle_clamps_to_min(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("machine.PWM")
    adapter = make_adapter(min_angle=0, max_angle=180)
    adapter.setup()

    adapter.set_angle(-10)

    assert adapter.angle() == 0


def test_set_angle_is_noop_when_unavailable(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("machine.PWM", side_effect=OSError("pwm unavailable"))
    adapter = make_adapter()
    adapter.setup()

    adapter.set_angle(45)

    assert adapter.angle() is None
    assert adapter.is_on() is False


def test_on_moves_to_default_angle(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("machine.PWM")
    adapter = make_adapter(default_angle=45)
    adapter.setup()

    adapter.on()

    assert adapter.angle() == 45
    assert adapter.is_on() is True


def test_off_zeroes_duty_and_clears_angle(mocker):
    mocker.patch("machine.Pin")
    mock_pwm_cls = mocker.patch("machine.PWM")
    adapter = make_adapter()
    adapter.setup()
    adapter.on()
    mock_pwm_cls.return_value.duty_u16.reset_mock()

    adapter.off()

    mock_pwm_cls.return_value.duty_u16.assert_called_once_with(0)
    assert adapter.angle() is None
    assert adapter.is_on() is False


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

    adapter.off()
    assert adapter.is_on() is False

    adapter.toggle()
    assert adapter.is_on() is False


def test_is_on_defaults_to_false():
    adapter = make_adapter()

    assert adapter.is_on() is False


def test_deinit_is_safe_when_setup_never_ran():
    adapter = make_adapter()

    adapter.deinit()

    assert adapter.available is False


def test_deinit_calls_pwm_deinit_and_resets_state(mocker):
    mocker.patch("machine.Pin")
    mock_pwm_cls = mocker.patch("machine.PWM")
    adapter = make_adapter()
    adapter.setup()
    adapter.on()

    adapter.deinit()

    mock_pwm_cls.return_value.deinit.assert_called_once_with()
    assert adapter.available is False
    assert adapter._pwm is None
    assert adapter.angle() is None
    assert adapter.is_on() is False


def test_deinit_survives_pwm_deinit_failure(mocker):
    mocker.patch("machine.Pin")
    mock_pwm_cls = mocker.patch("machine.PWM")
    mock_pwm_cls.return_value.deinit.side_effect = OSError("already gone")
    adapter = make_adapter()
    adapter.setup()

    adapter.deinit()

    assert adapter.available is False
    assert adapter._pwm is None
