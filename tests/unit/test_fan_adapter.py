from unittest.mock import MagicMock

from app.adapters.actuators.fan import FanAdapter


def make_adapter(in1_pin=2, in2_pin=4):
    return FanAdapter(in1_pin=in1_pin, in2_pin=in2_pin)


def patch_distinct_pins(mocker):
    """machine.Pin mocked bare returns the same MagicMock for every call, so
    self._in1 and self._in2 would alias the same mock and clobber each
    other's .value call history. side_effect gives each Pin() call its own
    mock, matching real hardware where in1/in2 are distinct GPIO pins."""
    mock_in1, mock_in2 = MagicMock(), MagicMock()
    mocker.patch("machine.Pin", side_effect=[mock_in1, mock_in2])
    return mock_in1, mock_in2


def test_setup_marks_available_and_starts_off(mocker):
    mock_pin_cls = mocker.patch("machine.Pin")

    adapter = make_adapter(in1_pin=2, in2_pin=4)
    adapter.setup()

    assert adapter.available is True
    assert mock_pin_cls.call_args_list == [
        mocker.call(2, mock_pin_cls.OUT),
        mocker.call(4, mock_pin_cls.OUT),
    ]
    assert adapter.is_on() is False


def test_setup_marks_unavailable_on_failure(mocker):
    mocker.patch("machine.Pin", side_effect=OSError("pin unavailable"))

    adapter = make_adapter()
    adapter.setup()

    assert adapter.available is False
    assert adapter._in1 is None
    assert adapter._in2 is None


def test_on_drives_forward(mocker):
    mock_in1, mock_in2 = patch_distinct_pins(mocker)
    adapter = make_adapter()
    adapter.setup()
    mock_in1.value.reset_mock()
    mock_in2.value.reset_mock()

    adapter.on()

    mock_in1.value.assert_called_once_with(1)
    mock_in2.value.assert_called_once_with(0)
    assert adapter.is_on() is True


def test_off_drives_both_pins_low(mocker):
    mock_in1, mock_in2 = patch_distinct_pins(mocker)
    adapter = make_adapter()
    adapter.setup()
    adapter.on()
    mock_in1.value.reset_mock()
    mock_in2.value.reset_mock()

    adapter.off()

    mock_in1.value.assert_called_once_with(0)
    mock_in2.value.assert_called_once_with(0)
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
    assert adapter._in1 is None
    assert adapter._in2 is None
    assert adapter.is_on() is False


# --------------------------------------------------------------------------
# cw / ccw / stop -- two-pin H-bridge direction control
# --------------------------------------------------------------------------


def test_direction_defaults_to_stop():
    adapter = make_adapter()

    assert adapter.direction() == "stop"


def test_cw_drives_in1_high_in2_low(mocker):
    mock_in1, mock_in2 = patch_distinct_pins(mocker)
    adapter = make_adapter()
    adapter.setup()
    mock_in1.value.reset_mock()
    mock_in2.value.reset_mock()

    adapter.cw()

    mock_in1.value.assert_called_once_with(1)
    mock_in2.value.assert_called_once_with(0)
    assert adapter.is_on() is True
    assert adapter.direction() == "cw"


def test_ccw_drives_in1_low_in2_high(mocker):
    mock_in1, mock_in2 = patch_distinct_pins(mocker)
    adapter = make_adapter()
    adapter.setup()
    mock_in1.value.reset_mock()
    mock_in2.value.reset_mock()

    adapter.ccw()

    mock_in1.value.assert_called_once_with(0)
    mock_in2.value.assert_called_once_with(1)
    assert adapter.is_on() is True
    assert adapter.direction() == "ccw"


def test_stop_drives_both_pins_low(mocker):
    mock_in1, mock_in2 = patch_distinct_pins(mocker)
    adapter = make_adapter()
    adapter.setup()
    adapter.cw()
    mock_in1.value.reset_mock()
    mock_in2.value.reset_mock()

    adapter.stop()

    mock_in1.value.assert_called_once_with(0)
    mock_in2.value.assert_called_once_with(0)
    assert adapter.is_on() is False
    assert adapter.direction() == "stop"


def test_ccw_then_cw_switches_direction_without_stopping_between(mocker):
    mock_in1, mock_in2 = patch_distinct_pins(mocker)
    adapter = make_adapter()
    adapter.setup()

    adapter.ccw()
    assert adapter.direction() == "ccw"

    adapter.cw()
    assert adapter.direction() == "cw"
    mock_in1.value.assert_called_with(1)
    mock_in2.value.assert_called_with(0)


def test_on_is_an_alias_for_cw(mocker):
    mock_in1, mock_in2 = patch_distinct_pins(mocker)
    adapter = make_adapter()
    adapter.setup()
    mock_in1.value.reset_mock()
    mock_in2.value.reset_mock()

    adapter.on()

    assert adapter.direction() == "cw"
    mock_in1.value.assert_called_once_with(1)
    mock_in2.value.assert_called_once_with(0)


def test_off_is_an_alias_for_stop(mocker):
    mock_in1, mock_in2 = patch_distinct_pins(mocker)
    adapter = make_adapter()
    adapter.setup()
    adapter.ccw()
    mock_in1.value.reset_mock()
    mock_in2.value.reset_mock()

    adapter.off()

    assert adapter.direction() == "stop"
    mock_in1.value.assert_called_once_with(0)
    mock_in2.value.assert_called_once_with(0)


def test_cw_ccw_stop_are_noops_when_unavailable(mocker):
    mocker.patch("machine.Pin", side_effect=OSError("pin unavailable"))
    adapter = make_adapter()
    adapter.setup()

    adapter.cw()
    assert adapter.direction() == "stop"

    adapter.ccw()
    assert adapter.direction() == "stop"

    adapter.stop()
    assert adapter.direction() == "stop"


def test_deinit_resets_direction_to_stop(mocker):
    mocker.patch("machine.Pin")
    adapter = make_adapter()
    adapter.setup()
    adapter.ccw()

    adapter.deinit()

    assert adapter.direction() == "stop"
