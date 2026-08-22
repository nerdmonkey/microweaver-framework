from app.adapters.sensors.gas_sensor import GasSensorAdapter


def make_adapter(pin=32, min_reading=0, max_reading=65535):
    return GasSensorAdapter(pin=pin, min_reading=min_reading, max_reading=max_reading)


def test_setup_marks_available_and_configures_attenuation(mocker):
    mock_pin_cls = mocker.patch("machine.Pin")
    mock_adc_cls = mocker.patch("machine.ADC")

    adapter = make_adapter(pin=32)
    adapter.setup()

    assert adapter.available is True
    mock_pin_cls.assert_called_once_with(32)
    mock_adc_cls.assert_called_once_with(mock_pin_cls.return_value)
    mock_adc_cls.return_value.atten.assert_called_once_with(mock_adc_cls.ATTN_11DB)


def test_setup_marks_unavailable_on_failure(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("machine.ADC", side_effect=OSError("adc unavailable"))

    adapter = make_adapter()
    adapter.setup()

    assert adapter.available is False
    assert adapter._adc is None


def test_read_returns_none_when_unavailable():
    adapter = make_adapter()

    assert adapter.read() is None


def test_read_returns_percent_from_raw_adc_value(mocker):
    mocker.patch("machine.Pin")
    mock_adc_cls = mocker.patch("machine.ADC")
    mock_adc_cls.return_value.read_u16.return_value = 32768
    adapter = make_adapter()
    adapter.setup()

    assert adapter.read() == 50.0


def test_read_clamps_above_max_to_100(mocker):
    mocker.patch("machine.Pin")
    mock_adc_cls = mocker.patch("machine.ADC")
    mock_adc_cls.return_value.read_u16.return_value = 70000
    adapter = make_adapter()
    adapter.setup()

    assert adapter.read() == 100.0


def test_read_clamps_below_min_to_0(mocker):
    mocker.patch("machine.Pin")
    mock_adc_cls = mocker.patch("machine.ADC")
    mock_adc_cls.return_value.read_u16.return_value = -100
    adapter = make_adapter()
    adapter.setup()

    assert adapter.read() == 0.0


def test_read_returns_none_on_adc_read_failure(mocker):
    mocker.patch("machine.Pin")
    mock_adc_cls = mocker.patch("machine.ADC")
    mock_adc_cls.return_value.read_u16.side_effect = OSError("read failed")
    adapter = make_adapter()
    adapter.setup()

    assert adapter.read() is None


def test_read_handles_zero_span_without_dividing_by_zero(mocker):
    mocker.patch("machine.Pin")
    mock_adc_cls = mocker.patch("machine.ADC")
    mock_adc_cls.return_value.read_u16.return_value = 100
    adapter = make_adapter(min_reading=100, max_reading=100)
    adapter.setup()

    assert adapter.read() == 0.0


def test_deinit_is_safe_when_setup_never_ran():
    adapter = make_adapter()

    adapter.deinit()

    assert adapter.available is False


def test_deinit_resets_state_after_setup(mocker):
    mocker.patch("machine.Pin")
    mocker.patch("machine.ADC")
    adapter = make_adapter()
    adapter.setup()

    adapter.deinit()

    assert adapter.available is False
    assert adapter._adc is None
