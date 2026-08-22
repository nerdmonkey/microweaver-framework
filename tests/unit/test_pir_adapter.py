from app.adapters.sensors.pir import PIRAdapter


def make_adapter(pin=34, warmup_seconds=10):
    return PIRAdapter(pin=pin, warmup_seconds=warmup_seconds)


def test_setup_marks_available_and_configures_input_pin(mocker):
    mocker.patch("time.time", return_value=1000)
    mock_pin_cls = mocker.patch("machine.Pin")

    adapter = make_adapter(pin=34, warmup_seconds=10)
    adapter.setup()

    assert adapter.available is True
    mock_pin_cls.assert_called_once_with(34, mock_pin_cls.IN)
    assert adapter._ready_at == 1010


def test_setup_marks_unavailable_on_failure(mocker):
    mocker.patch("machine.Pin", side_effect=OSError("pin unavailable"))

    adapter = make_adapter()
    adapter.setup()

    assert adapter.available is False
    assert adapter._sensor is None


def test_read_returns_none_when_unavailable():
    adapter = make_adapter()

    assert adapter.read() is None


def test_read_returns_none_during_warmup(mocker):
    mocker.patch("time.time", return_value=1000)
    mocker.patch("machine.Pin")
    adapter = make_adapter(warmup_seconds=10)
    adapter.setup()
    mocker.patch("time.time", return_value=1005)

    assert adapter.read() is None


def test_read_returns_bool_after_warmup(mocker):
    mocker.patch("time.time", return_value=1000)
    mock_pin_cls = mocker.patch("machine.Pin")
    mock_pin_cls.return_value.value.return_value = 1
    adapter = make_adapter(warmup_seconds=10)
    adapter.setup()
    mocker.patch("time.time", return_value=1010)

    assert adapter.read() is True


def test_read_returns_false_when_no_motion(mocker):
    mocker.patch("time.time", return_value=1000)
    mock_pin_cls = mocker.patch("machine.Pin")
    mock_pin_cls.return_value.value.return_value = 0
    adapter = make_adapter(warmup_seconds=10)
    adapter.setup()
    mocker.patch("time.time", return_value=1010)

    assert adapter.read() is False


def test_read_returns_none_on_read_failure(mocker):
    mocker.patch("time.time", return_value=1000)
    mock_pin_cls = mocker.patch("machine.Pin")
    mock_pin_cls.return_value.value.side_effect = OSError("read failed")
    adapter = make_adapter(warmup_seconds=10)
    adapter.setup()
    mocker.patch("time.time", return_value=1010)

    assert adapter.read() is None


def test_deinit_is_safe_when_setup_never_ran():
    adapter = make_adapter()

    adapter.deinit()

    assert adapter.available is False


def test_deinit_resets_state_after_setup(mocker):
    mocker.patch("time.time", return_value=1000)
    mocker.patch("machine.Pin")
    adapter = make_adapter()
    adapter.setup()

    adapter.deinit()

    assert adapter.available is False
    assert adapter._sensor is None
    assert adapter._ready_at is None
