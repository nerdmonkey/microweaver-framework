from app.adapters.sensors.dht22 import DHT22Adapter


def make_adapter(pin=4):
    return DHT22Adapter(pin=pin)


def test_setup_marks_available_on_success(mocker):
    mock_pin_cls = mocker.patch("machine.Pin")
    mock_dht22_cls = mocker.patch("dht.DHT22")

    adapter = make_adapter(pin=15)
    adapter.setup()

    assert adapter.available is True
    mock_pin_cls.assert_called_once_with(15)
    mock_dht22_cls.assert_called_once_with(mock_pin_cls.return_value)


def test_setup_marks_unavailable_on_failure(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("dht.DHT22", side_effect=OSError("sensor not found"))

    adapter = make_adapter()
    adapter.setup()

    assert adapter.available is False
    assert adapter._sensor is None


def test_read_returns_none_when_unavailable(mocker):
    mock_dht22_cls = mocker.patch("dht.DHT22")
    mocker.patch("machine.Pin")

    adapter = make_adapter()

    assert adapter.read() is None
    mock_dht22_cls.return_value.measure.assert_not_called()


def test_read_returns_temperature_and_humidity_on_success(mocker):
    mocker.patch("machine.Pin")
    mock_dht22_cls = mocker.patch("dht.DHT22")
    mock_sensor = mock_dht22_cls.return_value
    mock_sensor.temperature.return_value = 21.5
    mock_sensor.humidity.return_value = 55.0

    adapter = make_adapter()
    adapter.setup()

    assert adapter.read() == (21.5, 55.0)
    mock_sensor.measure.assert_called_once_with()
    assert adapter.temperature() == 21.5
    assert adapter.humidity() == 55.0


def test_read_returns_none_on_measure_failure(mocker):
    mocker.patch("machine.Pin")
    mock_dht22_cls = mocker.patch("dht.DHT22")
    mock_dht22_cls.return_value.measure.side_effect = OSError("checksum error")

    adapter = make_adapter()
    adapter.setup()

    assert adapter.read() is None


def test_temperature_and_humidity_default_to_none():
    adapter = make_adapter()

    assert adapter.temperature() is None
    assert adapter.humidity() is None


def test_deinit_is_safe_when_setup_never_ran():
    adapter = make_adapter()

    adapter.deinit()

    assert adapter.available is False


def test_deinit_resets_state_after_setup(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("dht.DHT22")

    adapter = make_adapter()
    adapter.setup()
    adapter.deinit()

    assert adapter.available is False
    assert adapter._sensor is None
