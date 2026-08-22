from app.adapters.actuators.auto_cycling_rgb import AutoCyclingRgbAdapter


def make_adapter(pin=15):
    return AutoCyclingRgbAdapter(pin=pin)


def test_setup_marks_available_and_starts_off(mocker):
    mock_pin_cls = mocker.patch("machine.Pin")

    adapter = make_adapter(pin=15)
    adapter.setup()

    assert adapter.available is True
    mock_pin_cls.assert_called_once_with(15, mock_pin_cls.OUT)
    assert adapter.is_on() is False
    assert mock_pin_cls.return_value.value.call_args == mocker.call(0)


def test_setup_marks_unavailable_on_failure(mocker):
    mocker.patch("machine.Pin", side_effect=OSError("pin unavailable"))

    adapter = make_adapter()
    adapter.setup()

    assert adapter.available is False
    assert adapter._enable is None


def test_on_sets_pin_high(mocker):
    mocker.patch("machine.Pin")
    adapter = make_adapter()
    adapter.setup()
    adapter._enable.value.reset_mock()

    adapter.on()

    adapter._enable.value.assert_called_once_with(1)
    assert adapter.is_on() is True


def test_off_sets_pin_low(mocker):
    mocker.patch("machine.Pin")
    adapter = make_adapter()
    adapter.setup()
    adapter.on()
    adapter._enable.value.reset_mock()

    adapter.off()

    adapter._enable.value.assert_called_once_with(0)
    assert adapter.is_on() is False


def test_toggle_switches_state(mocker):
    mocker.patch("machine.Pin")
    adapter = make_adapter()
    adapter.setup()

    adapter.toggle()
    assert adapter.is_on() is True

    adapter.toggle()
    assert adapter.is_on() is False


def test_on_off_toggle_are_noops_when_unavailable(mocker):
    mocker.patch("machine.Pin", side_effect=OSError("pin unavailable"))
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
    adapter = make_adapter()
    adapter.setup()
    adapter.on()

    adapter.deinit()

    assert adapter.available is False
    assert adapter._enable is None
    assert adapter.is_on() is False


def test_no_state_or_direction_method():
    """Deliberately no state()/direction() -- unlike RGBAdapter, this adapter
    can't report color (there isn't one to control), so
    RuntimeService._adapter_state_value() must fall back to the plain
    on/off boolean via is_on(), same as a relay."""
    adapter = make_adapter()

    assert not hasattr(adapter, "state")
    assert not hasattr(adapter, "direction")
    assert not hasattr(adapter, "set")
