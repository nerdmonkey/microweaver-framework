from app.adapters.actuators.relay import RelayAdapter


def make_adapter(pin=5, active_high=True):
    return RelayAdapter(pin=pin, active_high=active_high)


def test_setup_marks_available_and_starts_off(mocker):
    mock_pin_cls = mocker.patch("machine.Pin")

    adapter = make_adapter(pin=12)
    adapter.setup()

    assert adapter.available is True
    mock_pin_cls.assert_called_once_with(12, mock_pin_cls.OUT)
    mock_pin_cls.return_value.value.assert_called_once_with(0)
    assert adapter.is_on() is False


def test_setup_marks_unavailable_on_failure(mocker):
    mocker.patch("machine.Pin", side_effect=OSError("pin unavailable"))

    adapter = make_adapter()
    adapter.setup()

    assert adapter.available is False
    assert adapter._relay is None


def test_on_sets_active_high_value(mocker):
    mock_pin_cls = mocker.patch("machine.Pin")
    adapter = make_adapter(active_high=True)
    adapter.setup()
    mock_pin_cls.return_value.value.reset_mock()

    adapter.on()

    mock_pin_cls.return_value.value.assert_called_once_with(1)
    assert adapter.is_on() is True


def test_on_sets_active_low_value(mocker):
    mock_pin_cls = mocker.patch("machine.Pin")
    adapter = make_adapter(active_high=False)
    adapter.setup()
    mock_pin_cls.return_value.value.reset_mock()

    adapter.on()

    mock_pin_cls.return_value.value.assert_called_once_with(0)
    assert adapter.is_on() is True


def test_off_sets_active_high_value(mocker):
    mock_pin_cls = mocker.patch("machine.Pin")
    adapter = make_adapter(active_high=True)
    adapter.setup()
    adapter.on()
    mock_pin_cls.return_value.value.reset_mock()

    adapter.off()

    mock_pin_cls.return_value.value.assert_called_once_with(0)
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
    assert adapter._relay is None
    assert adapter.is_on() is False
