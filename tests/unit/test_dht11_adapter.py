from app.adapters.sensors.dht11 import DHT11Adapter


def make_adapter(pin=4):
    return DHT11Adapter(pin=pin)


def test_read_interval_seconds_matches_datasheet_minimum():
    assert DHT11Adapter.read_interval_seconds == 1


def test_setup_marks_available_on_success(mocker):
    mock_pin_cls = mocker.patch("machine.Pin")
    mock_dht11_cls = mocker.patch("dht.DHT11")

    adapter = make_adapter(pin=15)
    adapter.setup()

    assert adapter.available is True
    mock_pin_cls.assert_called_once_with(15)
    mock_dht11_cls.assert_called_once_with(mock_pin_cls.return_value)


def test_setup_marks_unavailable_on_failure(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("dht.DHT11", side_effect=OSError("sensor not found"))

    adapter = make_adapter()
    adapter.setup()

    assert adapter.available is False
    assert adapter._sensor is None


def test_read_returns_temperature_and_humidity_on_success(mocker):
    mocker.patch("machine.Pin")
    mock_dht11_cls = mocker.patch("dht.DHT11")
    mock_sensor = mock_dht11_cls.return_value
    mock_sensor.temperature.return_value = 21
    mock_sensor.humidity.return_value = 55

    adapter = make_adapter()
    adapter.setup()

    assert adapter.read() == (21, 55)
    mock_sensor.measure.assert_called_once_with()
    assert adapter.temperature() == 21
    assert adapter.humidity() == 55


def test_read_returns_none_on_measure_failure(mocker):
    mocker.patch("machine.Pin")
    mock_dht11_cls = mocker.patch("dht.DHT11")
    mock_dht11_cls.return_value.measure.side_effect = OSError("checksum error")

    adapter = make_adapter()
    adapter.setup()

    assert adapter.read() is None


def test_read_returns_none_when_never_set_up():
    adapter = make_adapter()

    assert adapter.read() is None


def test_deinit_clears_sensor_and_marks_unavailable(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("dht.DHT11")

    adapter = make_adapter()
    adapter.setup()
    adapter.deinit()

    assert adapter.available is False
    assert adapter._sensor is None
