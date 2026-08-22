import main


def _mock_topic_suffixes(mocker, **overrides):
    defaults = {
        "DHT_TEMPERATURE_TOPIC_SUFFIX": "temperature",
        "DHT_HUMIDITY_TOPIC_SUFFIX": "humidity",
        "RELAY_TOPIC_SUFFIX": "relay",
        "RGB_TOPIC_SUFFIX": "rgb",
        "OLED_TOPIC_SUFFIX": "oled",
        "POTENTIOMETER_TOPIC_SUFFIX": "potentiometer",
        "ROTARY_ANGLE_TOPIC_SUFFIX": "rotary_angle",
    }
    defaults.update(overrides)
    for attr, value in defaults.items():
        mocker.patch("main.setting.{}".format(attr), value)


def _mock_base_topics(mocker, pub="base/pub", sub="base/sub", status="base/status"):
    mocker.patch("main.setting.MQTT_TOPIC_PUB", [pub])
    mocker.patch("main.setting.MQTT_TOPIC_SUB", [sub])
    mocker.patch("main.setting.MQTT_TOPIC_STATUS", [status])


def test_start_wires_and_runs_runtime_service_with_dht22_default(mocker):
    _disable_existing_devices(mocker)
    mocker.patch("main.setting.DHT_ENABLED", True)
    mocker.patch("main.setting.DHT_PIN", 15)
    mocker.patch("main.setting.RELAY_ENABLED", True)
    mocker.patch("main.setting.RELAY_PIN", 16)
    mocker.patch("main.setting.RGB_ENABLED", False)
    mocker.patch("main.setting.DHT_SENSOR_TYPE", "dht22")
    mocker.patch("main.setting.OLED_ENABLED", False)
    mocker.patch("main.setting.POTENTIOMETER_ENABLED", False)
    mocker.patch("main.setting.ROTARY_ANGLE_ENABLED", False)
    _mock_topic_suffixes(mocker)
    _mock_base_topics(mocker)
    mock_dht22_cls = mocker.patch("main.DHT22Adapter")
    mock_dht11_cls = mocker.patch("main.DHT11Adapter")
    mock_relay_cls = mocker.patch("main.RelayAdapter")
    mock_runtime_cls = mocker.patch("main.RuntimeService")

    main.start()

    mock_dht22_cls.assert_called_once_with(pin=15)
    mock_dht11_cls.assert_not_called()
    mock_relay_cls.assert_called_once_with(pin=16)
    mock_runtime_cls.assert_called_once_with(
        publish_adapters=[("dht", mock_dht22_cls.return_value)],
        subscribe_adapters=[("relay", mock_relay_cls.return_value)],
        topics=["base/sub/relay"],
        topics_pub=["base/pub/temperature", "base/pub/humidity"],
        topics_status={"relay": "base/status/relay"},
        publish_intervals={},
    )
    mock_runtime_cls.return_value.run.assert_called_once_with()


def test_start_wires_and_runs_runtime_service_with_dht11(mocker):
    _disable_existing_devices(mocker)
    mocker.patch("main.setting.DHT_ENABLED", True)
    mocker.patch("main.setting.DHT_PIN", 15)
    mocker.patch("main.setting.RELAY_ENABLED", True)
    mocker.patch("main.setting.RELAY_PIN", 16)
    mocker.patch("main.setting.RGB_ENABLED", False)
    mocker.patch("main.setting.DHT_SENSOR_TYPE", "dht11")
    mocker.patch("main.setting.OLED_ENABLED", False)
    mocker.patch("main.setting.POTENTIOMETER_ENABLED", False)
    mocker.patch("main.setting.ROTARY_ANGLE_ENABLED", False)
    _mock_topic_suffixes(mocker)
    _mock_base_topics(mocker)
    mock_dht11_cls = mocker.patch("main.DHT11Adapter")
    mock_dht22_cls = mocker.patch("main.DHT22Adapter")
    mock_relay_cls = mocker.patch("main.RelayAdapter")
    mock_runtime_cls = mocker.patch("main.RuntimeService")

    main.start()

    mock_dht11_cls.assert_called_once_with(pin=15)
    mock_dht22_cls.assert_not_called()
    mock_relay_cls.assert_called_once_with(pin=16)
    mock_runtime_cls.assert_called_once_with(
        publish_adapters=[("dht", mock_dht11_cls.return_value)],
        subscribe_adapters=[("relay", mock_relay_cls.return_value)],
        topics=["base/sub/relay"],
        topics_pub=["base/pub/temperature", "base/pub/humidity"],
        topics_status={"relay": "base/status/relay"},
        publish_intervals={},
    )
    mock_runtime_cls.return_value.run.assert_called_once_with()


def test_start_uses_custom_dht_topic_suffixes(mocker):
    _disable_existing_devices(mocker)
    mocker.patch("main.setting.DHT_ENABLED", True)
    mocker.patch("main.setting.DHT_PIN", 15)
    mocker.patch("main.setting.RELAY_ENABLED", False)
    mocker.patch("main.setting.RGB_ENABLED", False)
    mocker.patch("main.setting.DHT_SENSOR_TYPE", "dht22")
    mocker.patch("main.setting.OLED_ENABLED", False)
    mocker.patch("main.setting.POTENTIOMETER_ENABLED", False)
    mocker.patch("main.setting.ROTARY_ANGLE_ENABLED", False)
    _mock_topic_suffixes(
        mocker,
        DHT_TEMPERATURE_TOPIC_SUFFIX="temp",
        DHT_HUMIDITY_TOPIC_SUFFIX="hum",
    )
    _mock_base_topics(mocker)
    mock_dht22_cls = mocker.patch("main.DHT22Adapter")
    mock_runtime_cls = mocker.patch("main.RuntimeService")

    main.start()

    mock_runtime_cls.assert_called_once_with(
        publish_adapters=[("dht", mock_dht22_cls.return_value)],
        subscribe_adapters=[],
        topics=[],
        topics_pub=["base/pub/temp", "base/pub/hum"],
        topics_status={},
        publish_intervals={},
    )


def test_start_skips_dht_adapter_when_disabled(mocker):
    _disable_existing_devices(mocker)
    mocker.patch("main.setting.DHT_ENABLED", False)
    mocker.patch("main.setting.RELAY_ENABLED", True)
    mocker.patch("main.setting.RELAY_PIN", 16)
    mocker.patch("main.setting.RGB_ENABLED", False)
    mocker.patch("main.setting.OLED_ENABLED", False)
    mocker.patch("main.setting.POTENTIOMETER_ENABLED", False)
    mocker.patch("main.setting.ROTARY_ANGLE_ENABLED", False)
    _mock_topic_suffixes(mocker)
    _mock_base_topics(mocker)
    mock_dht22_cls = mocker.patch("main.DHT22Adapter")
    mock_relay_cls = mocker.patch("main.RelayAdapter")
    mock_runtime_cls = mocker.patch("main.RuntimeService")

    main.start()

    mock_dht22_cls.assert_not_called()
    mock_runtime_cls.assert_called_once_with(
        publish_adapters=[],
        subscribe_adapters=[("relay", mock_relay_cls.return_value)],
        topics=["base/sub/relay"],
        topics_pub=[],
        topics_status={"relay": "base/status/relay"},
        publish_intervals={},
    )


def test_start_skips_relay_adapter_when_disabled(mocker):
    _disable_existing_devices(mocker)
    mocker.patch("main.setting.DHT_ENABLED", True)
    mocker.patch("main.setting.DHT_PIN", 15)
    mocker.patch("main.setting.DHT_SENSOR_TYPE", "dht22")
    mocker.patch("main.setting.RELAY_ENABLED", False)
    mocker.patch("main.setting.RGB_ENABLED", False)
    mocker.patch("main.setting.OLED_ENABLED", False)
    mocker.patch("main.setting.POTENTIOMETER_ENABLED", False)
    mocker.patch("main.setting.ROTARY_ANGLE_ENABLED", False)
    _mock_topic_suffixes(mocker)
    _mock_base_topics(mocker)
    mock_dht22_cls = mocker.patch("main.DHT22Adapter")
    mock_relay_cls = mocker.patch("main.RelayAdapter")
    mock_runtime_cls = mocker.patch("main.RuntimeService")

    main.start()

    mock_relay_cls.assert_not_called()
    mock_runtime_cls.assert_called_once_with(
        publish_adapters=[("dht", mock_dht22_cls.return_value)],
        subscribe_adapters=[],
        topics=[],
        topics_pub=["base/pub/temperature", "base/pub/humidity"],
        topics_status={},
        publish_intervals={},
    )


def test_start_wires_no_adapters_when_all_disabled(mocker):
    _disable_existing_devices(mocker)
    mocker.patch("main.setting.DHT_ENABLED", False)
    mocker.patch("main.setting.RELAY_ENABLED", False)
    mocker.patch("main.setting.RGB_ENABLED", False)
    mocker.patch("main.setting.OLED_ENABLED", False)
    mocker.patch("main.setting.POTENTIOMETER_ENABLED", False)
    mocker.patch("main.setting.ROTARY_ANGLE_ENABLED", False)
    _mock_topic_suffixes(mocker)
    _mock_base_topics(mocker)
    mock_dht22_cls = mocker.patch("main.DHT22Adapter")
    mock_relay_cls = mocker.patch("main.RelayAdapter")
    mock_rgb_cls = mocker.patch("main.RGBAdapter")
    mock_oled_cls = mocker.patch("main.OLEDAdapter")
    mock_runtime_cls = mocker.patch("main.RuntimeService")

    main.start()

    mock_dht22_cls.assert_not_called()
    mock_relay_cls.assert_not_called()
    mock_rgb_cls.assert_not_called()
    mock_oled_cls.assert_not_called()
    mock_runtime_cls.assert_called_once_with(
        publish_adapters=[],
        subscribe_adapters=[],
        topics=[],
        topics_pub=[],
        topics_status={},
        publish_intervals={},
    )


def test_start_wires_rgb_adapter_when_enabled(mocker):
    _disable_existing_devices(mocker)
    mocker.patch("main.setting.DHT_ENABLED", False)
    mocker.patch("main.setting.RELAY_ENABLED", False)
    mocker.patch("main.setting.RGB_ENABLED", True)
    mocker.patch("main.setting.RGB_RED_PIN", 25)
    mocker.patch("main.setting.RGB_GREEN_PIN", 26)
    mocker.patch("main.setting.RGB_BLUE_PIN", 27)
    mocker.patch("main.setting.OLED_ENABLED", False)
    mocker.patch("main.setting.POTENTIOMETER_ENABLED", False)
    mocker.patch("main.setting.ROTARY_ANGLE_ENABLED", False)
    _mock_topic_suffixes(mocker)
    _mock_base_topics(mocker)
    mock_rgb_cls = mocker.patch("main.RGBAdapter")
    mock_runtime_cls = mocker.patch("main.RuntimeService")

    main.start()

    mock_rgb_cls.assert_called_once_with(red_pin=25, green_pin=26, blue_pin=27)
    mock_runtime_cls.assert_called_once_with(
        publish_adapters=[],
        subscribe_adapters=[("rgb", mock_rgb_cls.return_value)],
        topics=["base/sub/rgb"],
        topics_pub=[],
        topics_status={"rgb": "base/status/rgb"},
        publish_intervals={},
    )


def test_start_wires_auto_cycling_rgb_adapter_when_mode_set(mocker):
    _disable_existing_devices(mocker)
    mocker.patch("main.setting.RGB_ENABLED", True)
    mocker.patch("main.setting.RGB_MODE", "auto_cycling")
    mocker.patch("main.setting.RGB_RED_PIN", 15)
    _mock_topic_suffixes(mocker)
    _mock_base_topics(mocker)
    mock_rgb_cls = mocker.patch("main.RGBAdapter")
    mock_auto_cycling_cls = mocker.patch("main.AutoCyclingRgbAdapter")
    mock_runtime_cls = mocker.patch("main.RuntimeService")

    main.start()

    mock_rgb_cls.assert_not_called()
    mock_auto_cycling_cls.assert_called_once_with(pin=15)
    mock_runtime_cls.assert_called_once_with(
        publish_adapters=[],
        subscribe_adapters=[("rgb", mock_auto_cycling_cls.return_value)],
        topics=["base/sub/rgb"],
        topics_pub=[],
        topics_status={"rgb": "base/status/rgb"},
        publish_intervals={},
    )


def test_start_skips_rgb_adapter_when_disabled(mocker):
    _disable_existing_devices(mocker)
    mocker.patch("main.setting.DHT_ENABLED", False)
    mocker.patch("main.setting.RELAY_ENABLED", True)
    mocker.patch("main.setting.RELAY_PIN", 16)
    mocker.patch("main.setting.RGB_ENABLED", False)
    mocker.patch("main.setting.OLED_ENABLED", False)
    mocker.patch("main.setting.POTENTIOMETER_ENABLED", False)
    mocker.patch("main.setting.ROTARY_ANGLE_ENABLED", False)
    _mock_topic_suffixes(mocker)
    _mock_base_topics(mocker)
    mock_relay_cls = mocker.patch("main.RelayAdapter")
    mock_rgb_cls = mocker.patch("main.RGBAdapter")
    mock_runtime_cls = mocker.patch("main.RuntimeService")

    main.start()

    mock_rgb_cls.assert_not_called()
    mock_runtime_cls.assert_called_once_with(
        publish_adapters=[],
        subscribe_adapters=[("relay", mock_relay_cls.return_value)],
        topics=["base/sub/relay"],
        topics_pub=[],
        topics_status={"relay": "base/status/relay"},
        publish_intervals={},
    )


def test_start_wires_relay_and_rgb_together(mocker):
    _disable_existing_devices(mocker)
    mocker.patch("main.setting.DHT_ENABLED", False)
    mocker.patch("main.setting.RELAY_ENABLED", True)
    mocker.patch("main.setting.RELAY_PIN", 16)
    mocker.patch("main.setting.RGB_ENABLED", True)
    mocker.patch("main.setting.RGB_RED_PIN", 25)
    mocker.patch("main.setting.RGB_GREEN_PIN", 26)
    mocker.patch("main.setting.RGB_BLUE_PIN", 27)
    mocker.patch("main.setting.OLED_ENABLED", False)
    mocker.patch("main.setting.POTENTIOMETER_ENABLED", False)
    mocker.patch("main.setting.ROTARY_ANGLE_ENABLED", False)
    _mock_topic_suffixes(mocker)
    _mock_base_topics(mocker)
    mock_relay_cls = mocker.patch("main.RelayAdapter")
    mock_rgb_cls = mocker.patch("main.RGBAdapter")
    mock_runtime_cls = mocker.patch("main.RuntimeService")

    main.start()

    mock_runtime_cls.assert_called_once_with(
        publish_adapters=[],
        subscribe_adapters=[
            ("relay", mock_relay_cls.return_value),
            ("rgb", mock_rgb_cls.return_value),
        ],
        topics=["base/sub/relay", "base/sub/rgb"],
        topics_pub=[],
        topics_status={"relay": "base/status/relay", "rgb": "base/status/rgb"},
        publish_intervals={},
    )


def test_start_wires_oled_adapter_when_enabled(mocker):
    _disable_existing_devices(mocker)
    mocker.patch("main.setting.DHT_ENABLED", False)
    mocker.patch("main.setting.RELAY_ENABLED", False)
    mocker.patch("main.setting.RGB_ENABLED", False)
    mocker.patch("main.setting.OLED_ENABLED", True)
    mocker.patch("main.setting.POTENTIOMETER_ENABLED", False)
    mocker.patch("main.setting.ROTARY_ANGLE_ENABLED", False)
    mocker.patch("main.setting.OLED_SDA_PIN", 21)
    mocker.patch("main.setting.OLED_SCL_PIN", 22)
    mocker.patch("main.setting.OLED_I2C_ADDR", 0x3C)
    mocker.patch("main.setting.OLED_WIDTH", 128)
    mocker.patch("main.setting.OLED_HEIGHT", 64)
    _mock_topic_suffixes(mocker)
    _mock_base_topics(mocker)
    mock_oled_cls = mocker.patch("main.OLEDAdapter")
    mock_runtime_cls = mocker.patch("main.RuntimeService")

    main.start()

    mock_oled_cls.assert_called_once_with(
        sda_pin=21, scl_pin=22, i2c_addr=0x3C, width=128, height=64
    )
    mock_runtime_cls.assert_called_once_with(
        publish_adapters=[],
        subscribe_adapters=[("oled", mock_oled_cls.return_value)],
        topics=["base/sub/oled"],
        topics_pub=[],
        topics_status={},
        publish_intervals={},
    )


def test_start_skips_oled_adapter_when_disabled(mocker):
    _disable_existing_devices(mocker)
    mocker.patch("main.setting.DHT_ENABLED", False)
    mocker.patch("main.setting.RELAY_ENABLED", True)
    mocker.patch("main.setting.RELAY_PIN", 16)
    mocker.patch("main.setting.RGB_ENABLED", False)
    mocker.patch("main.setting.OLED_ENABLED", False)
    mocker.patch("main.setting.POTENTIOMETER_ENABLED", False)
    mocker.patch("main.setting.ROTARY_ANGLE_ENABLED", False)
    _mock_topic_suffixes(mocker)
    _mock_base_topics(mocker)
    mock_relay_cls = mocker.patch("main.RelayAdapter")
    mock_oled_cls = mocker.patch("main.OLEDAdapter")
    mock_runtime_cls = mocker.patch("main.RuntimeService")

    main.start()

    mock_oled_cls.assert_not_called()
    mock_runtime_cls.assert_called_once_with(
        publish_adapters=[],
        subscribe_adapters=[("relay", mock_relay_cls.return_value)],
        topics=["base/sub/relay"],
        topics_pub=[],
        topics_status={"relay": "base/status/relay"},
        publish_intervals={},
    )


def test_start_wires_relay_and_oled_together(mocker):
    _disable_existing_devices(mocker)
    mocker.patch("main.setting.DHT_ENABLED", False)
    mocker.patch("main.setting.RELAY_ENABLED", True)
    mocker.patch("main.setting.RELAY_PIN", 16)
    mocker.patch("main.setting.RGB_ENABLED", False)
    mocker.patch("main.setting.OLED_ENABLED", True)
    mocker.patch("main.setting.POTENTIOMETER_ENABLED", False)
    mocker.patch("main.setting.ROTARY_ANGLE_ENABLED", False)
    mocker.patch("main.setting.OLED_SDA_PIN", 21)
    mocker.patch("main.setting.OLED_SCL_PIN", 22)
    mocker.patch("main.setting.OLED_I2C_ADDR", 0x3C)
    mocker.patch("main.setting.OLED_WIDTH", 128)
    mocker.patch("main.setting.OLED_HEIGHT", 64)
    _mock_topic_suffixes(mocker)
    _mock_base_topics(mocker)
    mock_relay_cls = mocker.patch("main.RelayAdapter")
    mock_oled_cls = mocker.patch("main.OLEDAdapter")
    mock_runtime_cls = mocker.patch("main.RuntimeService")

    main.start()

    mock_runtime_cls.assert_called_once_with(
        publish_adapters=[],
        subscribe_adapters=[
            ("relay", mock_relay_cls.return_value),
            ("oled", mock_oled_cls.return_value),
        ],
        topics=["base/sub/relay", "base/sub/oled"],
        topics_pub=[],
        topics_status={"relay": "base/status/relay"},
        publish_intervals={},
    )


def test_start_wires_potentiometer_adapter_when_enabled(mocker):
    _disable_existing_devices(mocker)
    mocker.patch("main.setting.DHT_ENABLED", False)
    mocker.patch("main.setting.RELAY_ENABLED", False)
    mocker.patch("main.setting.RGB_ENABLED", False)
    mocker.patch("main.setting.OLED_ENABLED", False)
    mocker.patch("main.setting.POTENTIOMETER_ENABLED", True)
    mocker.patch("main.setting.POTENTIOMETER_PIN", 34)
    mocker.patch("main.setting.ROTARY_ANGLE_ENABLED", False)
    _mock_topic_suffixes(mocker)
    _mock_base_topics(mocker)
    mock_pot_cls = mocker.patch("main.PotentiometerAdapter")
    mock_runtime_cls = mocker.patch("main.RuntimeService")

    main.start()

    mock_pot_cls.assert_called_once_with(pin=34)
    mock_runtime_cls.assert_called_once_with(
        publish_adapters=[("potentiometer", mock_pot_cls.return_value)],
        subscribe_adapters=[],
        topics=[],
        topics_pub=["base/pub/potentiometer"],
        topics_status={},
        publish_intervals={},
    )


def test_start_wires_rotary_angle_adapter_when_enabled(mocker):
    _disable_existing_devices(mocker)
    mocker.patch("main.setting.DHT_ENABLED", False)
    mocker.patch("main.setting.RELAY_ENABLED", False)
    mocker.patch("main.setting.RGB_ENABLED", False)
    mocker.patch("main.setting.OLED_ENABLED", False)
    mocker.patch("main.setting.POTENTIOMETER_ENABLED", False)
    mocker.patch("main.setting.ROTARY_ANGLE_ENABLED", True)
    mocker.patch("main.setting.ROTARY_ANGLE_PIN", 35)
    _mock_topic_suffixes(mocker)
    _mock_base_topics(mocker)
    mock_rotary_cls = mocker.patch("main.RotaryAngleAdapter")
    mock_runtime_cls = mocker.patch("main.RuntimeService")

    main.start()

    mock_rotary_cls.assert_called_once_with(pin=35)
    mock_runtime_cls.assert_called_once_with(
        publish_adapters=[("rotary_angle", mock_rotary_cls.return_value)],
        subscribe_adapters=[],
        topics=[],
        topics_pub=["base/pub/rotary_angle"],
        topics_status={},
        publish_intervals={},
    )


def test_start_skips_potentiometer_and_rotary_angle_when_disabled(mocker):
    _disable_existing_devices(mocker)
    mocker.patch("main.setting.DHT_ENABLED", True)
    mocker.patch("main.setting.DHT_PIN", 15)
    mocker.patch("main.setting.DHT_SENSOR_TYPE", "dht22")
    mocker.patch("main.setting.RELAY_ENABLED", False)
    mocker.patch("main.setting.RGB_ENABLED", False)
    mocker.patch("main.setting.OLED_ENABLED", False)
    mocker.patch("main.setting.POTENTIOMETER_ENABLED", False)
    mocker.patch("main.setting.ROTARY_ANGLE_ENABLED", False)
    _mock_topic_suffixes(mocker)
    _mock_base_topics(mocker)
    mock_dht22_cls = mocker.patch("main.DHT22Adapter")
    mock_pot_cls = mocker.patch("main.PotentiometerAdapter")
    mock_rotary_cls = mocker.patch("main.RotaryAngleAdapter")
    mock_runtime_cls = mocker.patch("main.RuntimeService")

    main.start()

    mock_pot_cls.assert_not_called()
    mock_rotary_cls.assert_not_called()
    mock_runtime_cls.assert_called_once_with(
        publish_adapters=[("dht", mock_dht22_cls.return_value)],
        subscribe_adapters=[],
        topics=[],
        topics_pub=["base/pub/temperature", "base/pub/humidity"],
        topics_status={},
        publish_intervals={},
    )


def test_start_wires_potentiometer_and_rotary_angle_together_with_dht(mocker):
    _disable_existing_devices(mocker)
    mocker.patch("main.setting.DHT_ENABLED", True)
    mocker.patch("main.setting.DHT_PIN", 15)
    mocker.patch("main.setting.DHT_SENSOR_TYPE", "dht22")
    mocker.patch("main.setting.RELAY_ENABLED", False)
    mocker.patch("main.setting.RGB_ENABLED", False)
    mocker.patch("main.setting.OLED_ENABLED", False)
    mocker.patch("main.setting.POTENTIOMETER_ENABLED", True)
    mocker.patch("main.setting.POTENTIOMETER_PIN", 34)
    mocker.patch("main.setting.ROTARY_ANGLE_ENABLED", True)
    mocker.patch("main.setting.ROTARY_ANGLE_PIN", 35)
    _mock_topic_suffixes(mocker)
    _mock_base_topics(mocker)
    mock_dht22_cls = mocker.patch("main.DHT22Adapter")
    mock_pot_cls = mocker.patch("main.PotentiometerAdapter")
    mock_rotary_cls = mocker.patch("main.RotaryAngleAdapter")
    mock_runtime_cls = mocker.patch("main.RuntimeService")

    main.start()

    mock_runtime_cls.assert_called_once_with(
        publish_adapters=[
            ("dht", mock_dht22_cls.return_value),
            ("potentiometer", mock_pot_cls.return_value),
            ("rotary_angle", mock_rotary_cls.return_value),
        ],
        subscribe_adapters=[],
        topics=[],
        topics_pub=[
            "base/pub/temperature",
            "base/pub/humidity",
            "base/pub/potentiometer",
            "base/pub/rotary_angle",
        ],
        topics_status={},
        publish_intervals={},
    )


def _disable_existing_devices(mocker):
    mocker.patch("main.setting.UNIFIED_MQTT_CONTRACT_ENABLED", False)
    mocker.patch("main.setting.DHT_ENABLED", False)
    mocker.patch("main.setting.RELAY_ENABLED", False)
    mocker.patch("main.setting.RGB_ENABLED", False)
    mocker.patch("main.setting.RGB_MODE", "controllable")
    mocker.patch("main.setting.OLED_ENABLED", False)
    mocker.patch("main.setting.POTENTIOMETER_ENABLED", False)
    mocker.patch("main.setting.ROTARY_ANGLE_ENABLED", False)
    mocker.patch("main.setting.LCD_ENABLED", False)
    mocker.patch("main.setting.SERVO_ENABLED", False)
    mocker.patch("main.setting.PIR_ENABLED", False)
    mocker.patch("main.setting.FAN_ENABLED", False)
    mocker.patch("main.setting.OUTDOOR_LIGHT_ENABLED", False)
    mocker.patch("main.setting.BUZZER_ENABLED", False)
    mocker.patch("main.setting.CO_SENSOR_ENABLED", False)
    mocker.patch("main.setting.GAS_SENSOR_ENABLED", False)


def test_start_wires_pir_adapter_when_enabled(mocker):
    _disable_existing_devices(mocker)
    mocker.patch("main.setting.PIR_ENABLED", True)
    mocker.patch("main.setting.PIR_PIN", 34)
    mocker.patch("main.setting.PIR_WARMUP_SECONDS", 10)
    _mock_topic_suffixes(mocker)
    _mock_base_topics(mocker)
    mock_pir_cls = mocker.patch("main.PIRAdapter")
    mock_runtime_cls = mocker.patch("main.RuntimeService")

    main.start()

    mock_pir_cls.assert_called_once_with(pin=34, warmup_seconds=10)
    mock_runtime_cls.assert_called_once_with(
        publish_adapters=[("pir", mock_pir_cls.return_value)],
        subscribe_adapters=[],
        topics=[],
        topics_pub=["base/pub/pir"],
        topics_status={},
        publish_intervals={},
    )


def test_start_wires_co_sensor_adapter_with_heartbeat_interval(mocker):
    _disable_existing_devices(mocker)
    mocker.patch("main.setting.CO_SENSOR_ENABLED", True)
    mocker.patch("main.setting.CO_SENSOR_PIN", 35)
    mocker.patch("main.setting.CO_SENSOR_HEARTBEAT_SECONDS", 30)
    _mock_topic_suffixes(mocker)
    _mock_base_topics(mocker)
    mock_co_cls = mocker.patch("main.CoSensorAdapter")
    mock_runtime_cls = mocker.patch("main.RuntimeService")

    main.start()

    mock_co_cls.assert_called_once_with(pin=35)
    mock_runtime_cls.assert_called_once_with(
        publish_adapters=[("co_sensor", mock_co_cls.return_value)],
        subscribe_adapters=[],
        topics=[],
        topics_pub=["base/pub/co_sensor"],
        topics_status={},
        publish_intervals={"co_sensor": 30},
    )


def test_start_wires_gas_sensor_adapter_with_heartbeat_interval(mocker):
    _disable_existing_devices(mocker)
    mocker.patch("main.setting.GAS_SENSOR_ENABLED", True)
    mocker.patch("main.setting.GAS_SENSOR_PIN", 32)
    mocker.patch("main.setting.GAS_SENSOR_HEARTBEAT_SECONDS", 30)
    _mock_topic_suffixes(mocker)
    _mock_base_topics(mocker)
    mock_gas_cls = mocker.patch("main.GasSensorAdapter")
    mock_runtime_cls = mocker.patch("main.RuntimeService")

    main.start()

    mock_gas_cls.assert_called_once_with(pin=32)
    mock_runtime_cls.assert_called_once_with(
        publish_adapters=[("gas_sensor", mock_gas_cls.return_value)],
        subscribe_adapters=[],
        topics=[],
        topics_pub=["base/pub/gas_sensor"],
        topics_status={},
        publish_intervals={"gas_sensor": 30},
    )


def test_start_wires_lcd_adapter_when_enabled(mocker):
    _disable_existing_devices(mocker)
    mocker.patch("main.setting.LCD_ENABLED", True)
    mocker.patch("main.setting.LCD_SDA_PIN", 22)
    mocker.patch("main.setting.LCD_SCL_PIN", 21)
    mocker.patch("main.setting.LCD_I2C_ADDR", 0x3E)
    mocker.patch("main.setting.LCD_RGB_ADDR", 0x62)
    mocker.patch("main.setting.LCD_COLS", 16)
    mocker.patch("main.setting.LCD_ROWS", 2)
    mocker.patch("main.setting.LCD_I2C_ID", 0)
    mocker.patch("main.setting.MQTT_USERNAME", "dev_fa6648eb")
    _mock_topic_suffixes(mocker)
    _mock_base_topics(mocker)
    mock_lcd_cls = mocker.patch("main.LCDAdapter")
    mock_runtime_cls = mocker.patch("main.RuntimeService")

    main.start()

    mock_lcd_cls.assert_called_once_with(
        sda_pin=22,
        scl_pin=21,
        i2c_addr=0x3E,
        rgb_addr=0x62,
        cols=16,
        rows=2,
        i2c_id=0,
        default_lines=["Agnes Smart Home", "dev_fa6648eb"],
    )
    mock_runtime_cls.assert_called_once_with(
        publish_adapters=[],
        subscribe_adapters=[("lcd", mock_lcd_cls.return_value)],
        topics=["base/sub/lcd"],
        topics_pub=[],
        topics_status={"lcd": "base/status/lcd"},
        publish_intervals={},
    )


def test_start_wires_servo_adapter_when_enabled(mocker):
    _disable_existing_devices(mocker)
    mocker.patch("main.setting.SERVO_ENABLED", True)
    mocker.patch("main.setting.SERVO_PIN", 13)
    mocker.patch("main.setting.SERVO_DEFAULT_ANGLE", 90)
    _mock_topic_suffixes(mocker)
    _mock_base_topics(mocker)
    mock_servo_cls = mocker.patch("main.ServoAdapter")
    mock_runtime_cls = mocker.patch("main.RuntimeService")

    main.start()

    mock_servo_cls.assert_called_once_with(pin=13, default_angle=90)
    mock_runtime_cls.assert_called_once_with(
        publish_adapters=[],
        subscribe_adapters=[("servo", mock_servo_cls.return_value)],
        topics=["base/sub/servo"],
        topics_pub=[],
        topics_status={"servo": "base/status/servo"},
        publish_intervals={},
    )


def test_start_wires_fan_adapter_when_enabled(mocker):
    _disable_existing_devices(mocker)
    mocker.patch("main.setting.FAN_ENABLED", True)
    mocker.patch("main.setting.FAN_IN1_PIN", 2)
    mocker.patch("main.setting.FAN_IN2_PIN", 4)
    _mock_topic_suffixes(mocker)
    _mock_base_topics(mocker)
    mock_fan_cls = mocker.patch("main.FanAdapter")
    mock_runtime_cls = mocker.patch("main.RuntimeService")

    main.start()

    mock_fan_cls.assert_called_once_with(in1_pin=2, in2_pin=4)
    mock_runtime_cls.assert_called_once_with(
        publish_adapters=[],
        subscribe_adapters=[("fan", mock_fan_cls.return_value)],
        topics=["base/sub/fan"],
        topics_pub=[],
        topics_status={"fan": "base/status/fan"},
        publish_intervals={},
    )


def test_start_wires_outdoor_light_adapter_when_enabled(mocker):
    _disable_existing_devices(mocker)
    mocker.patch("main.setting.OUTDOOR_LIGHT_ENABLED", True)
    mocker.patch("main.setting.OUTDOOR_LIGHT_PIN", 17)
    _mock_topic_suffixes(mocker)
    _mock_base_topics(mocker)
    mock_relay_cls = mocker.patch("main.RelayAdapter")
    mock_runtime_cls = mocker.patch("main.RuntimeService")

    main.start()

    mock_relay_cls.assert_called_once_with(pin=17)
    mock_runtime_cls.assert_called_once_with(
        publish_adapters=[],
        subscribe_adapters=[("outdoor_light", mock_relay_cls.return_value)],
        topics=["base/sub/outdoor_light"],
        topics_pub=[],
        topics_status={"outdoor_light": "base/status/outdoor_light"},
        publish_intervals={},
    )


def test_start_wires_buzzer_adapter_when_enabled(mocker):
    _disable_existing_devices(mocker)
    mocker.patch("main.setting.BUZZER_ENABLED", True)
    mocker.patch("main.setting.BUZZER_PIN", 19)
    _mock_topic_suffixes(mocker)
    _mock_base_topics(mocker)
    mock_relay_cls = mocker.patch("main.RelayAdapter")
    mock_runtime_cls = mocker.patch("main.RuntimeService")

    main.start()

    mock_relay_cls.assert_called_once_with(pin=19)
    mock_runtime_cls.assert_called_once_with(
        publish_adapters=[],
        subscribe_adapters=[("buzzer", mock_relay_cls.return_value)],
        topics=["base/sub/buzzer"],
        topics_pub=[],
        topics_status={"buzzer": "base/status/buzzer"},
        publish_intervals={},
    )


def test_start_wires_unified_mode_with_no_topic_kwargs(mocker):
    _disable_existing_devices(mocker)
    mocker.patch("main.setting.UNIFIED_MQTT_CONTRACT_ENABLED", True)
    mocker.patch("main.setting.RELAY_ENABLED", True)
    mocker.patch("main.setting.RELAY_PIN", 16)
    mocker.patch("main.setting.POTENTIOMETER_ENABLED", True)
    mocker.patch("main.setting.POTENTIOMETER_PIN", 34)
    _mock_topic_suffixes(mocker)
    mock_relay_cls = mocker.patch("main.RelayAdapter")
    mock_pot_cls = mocker.patch("main.PotentiometerAdapter")
    mock_runtime_cls = mocker.patch("main.RuntimeService")

    main.start()

    mock_relay_cls.assert_called_once_with(pin=16)
    mock_pot_cls.assert_called_once_with(pin=34)
    mock_runtime_cls.assert_called_once_with(
        publish_adapters=[("potentiometer", mock_pot_cls.return_value)],
        subscribe_adapters=[("relay", mock_relay_cls.return_value)],
        publish_intervals={},
        unified_mode=True,
    )
    mock_runtime_cls.return_value.run.assert_called_once_with()


def test_start_unified_mode_wires_co_and_gas_sensor_heartbeat_intervals(mocker):
    _disable_existing_devices(mocker)
    mocker.patch("main.setting.UNIFIED_MQTT_CONTRACT_ENABLED", True)
    mocker.patch("main.setting.CO_SENSOR_ENABLED", True)
    mocker.patch("main.setting.CO_SENSOR_PIN", 36)
    mocker.patch("main.setting.CO_SENSOR_HEARTBEAT_SECONDS", 45)
    mocker.patch("main.setting.GAS_SENSOR_ENABLED", True)
    mocker.patch("main.setting.GAS_SENSOR_PIN", 39)
    mocker.patch("main.setting.GAS_SENSOR_HEARTBEAT_SECONDS", 15)
    mocker.patch("main.CoSensorAdapter")
    mocker.patch("main.GasSensorAdapter")
    mock_runtime_cls = mocker.patch("main.RuntimeService")

    main.start()

    assert mock_runtime_cls.call_args.kwargs["publish_intervals"] == {
        "co_sensor": 45,
        "gas_sensor": 15,
    }
    assert mock_runtime_cls.call_args.kwargs["unified_mode"] is True


def test_start_uses_legacy_mode_when_unified_disabled(mocker):
    _disable_existing_devices(mocker)
    mocker.patch("main.setting.UNIFIED_MQTT_CONTRACT_ENABLED", False)
    mocker.patch("main.setting.RELAY_ENABLED", True)
    mocker.patch("main.setting.RELAY_PIN", 16)
    _mock_topic_suffixes(mocker)
    _mock_base_topics(mocker)
    mocker.patch("main.RelayAdapter")
    mock_runtime_cls = mocker.patch("main.RuntimeService")

    main.start()

    assert "unified_mode" not in mock_runtime_cls.call_args.kwargs
    assert mock_runtime_cls.call_args.kwargs["topics_pub"] == []


def test_start_safe_mode_wires_and_runs_safe_mode_service(mocker):
    mocker.patch("main.setting.SAFE_MODE_SLEEP_SECONDS", 7)
    mock_safe_mode_cls = mocker.patch("main.SafeModeService")
    mock_instance = mock_safe_mode_cls.return_value

    main.start_safe_mode()

    mock_safe_mode_cls.assert_called_once_with(7)
    mock_instance.run.assert_called_once_with()


def test_start_provisioning_wires_and_runs_provisioning_service(mocker):
    mocker.patch("main.setting.PROVISIONING_AP_SSID", "Microweaver-Setup")
    mocker.patch("main.setting.PROVISIONING_AP_PASSWORD", "secret123")
    mocker.patch("main.setting.PROVISIONING_AP_IP", "192.168.4.1")
    mocker.patch("main.setting.PROVISIONING_PORT", 80)
    mocker.patch("main.setting.PROVISIONING_LED_ENABLED", False)
    mock_led_cls = mocker.patch("main.StatusLEDAdapter")
    mock_provisioning_cls = mocker.patch("main.ProvisioningService")
    mock_instance = mock_provisioning_cls.return_value

    main.start_provisioning()

    mock_led_cls.assert_not_called()
    mock_provisioning_cls.assert_called_once_with(
        ap_ssid="Microweaver-Setup",
        ap_password="secret123",
        ap_ip="192.168.4.1",
        port=80,
        setting=main.setting,
        led=None,
    )
    mock_instance.run.assert_called_once_with()


def test_start_provisioning_wires_led_when_enabled(mocker):
    mocker.patch("main.setting.PROVISIONING_AP_SSID", "Microweaver-Setup")
    mocker.patch("main.setting.PROVISIONING_AP_PASSWORD", "secret123")
    mocker.patch("main.setting.PROVISIONING_AP_IP", "192.168.4.1")
    mocker.patch("main.setting.PROVISIONING_PORT", 80)
    mocker.patch("main.setting.PROVISIONING_LED_ENABLED", True)
    mocker.patch("main.setting.PROVISIONING_LED_PIN", 12)
    mock_led_cls = mocker.patch("main.StatusLEDAdapter")
    mock_led = mock_led_cls.return_value
    mock_provisioning_cls = mocker.patch("main.ProvisioningService")
    mock_instance = mock_provisioning_cls.return_value

    main.start_provisioning()

    mock_led_cls.assert_called_once_with(pin=12)
    mock_led.setup.assert_called_once_with()
    mock_provisioning_cls.assert_called_once_with(
        ap_ssid="Microweaver-Setup",
        ap_password="secret123",
        ap_ip="192.168.4.1",
        port=80,
        setting=main.setting,
        led=mock_led,
    )
    mock_instance.run.assert_called_once_with()
    mock_led.deinit.assert_called_once_with()


def test_start_claim_wires_wifi_and_registers_with_backend(mocker):
    mocker.patch("main.setting.WIFI_SSID", "TestNet")
    mocker.patch("main.setting.WIFI_PASSWORD", "secret")
    mocker.patch("main.setting.WIFI_CONNECT_TIMEOUT_SECONDS", 20)
    mocker.patch("main.setting.WIFI_RECONNECT_DELAY_SECONDS", 2)
    mocker.patch("main.setting.WIFI_MAX_RECONNECT_DELAY_SECONDS", 30)
    mocker.patch("main.setting.WIFI_DISABLE_POWER_SAVE", False)
    mocker.patch("main.setting.CLAIM_URL", "https://api.example.com/devices")
    mocker.patch("main.setting.CLAIM_CODE", "CODE123")
    mock_wifi_cls = mocker.patch("main.WiFiService")
    mock_registration_cls = mocker.patch("main.RegistrationService")

    main.start_claim()

    mock_wifi_cls.assert_called_once_with(
        ssid="TestNet",
        password="secret",
        connect_timeout_seconds=20,
        reconnect_delay_seconds=2,
        max_reconnect_delay_seconds=30,
        disable_power_save=False,
    )
    mock_wifi_cls.return_value.connect.assert_called_once_with()
    mock_registration_cls.assert_called_once_with(
        claim_url="https://api.example.com/devices",
        claim_code="CODE123",
        setting=main.setting,
    )
    mock_registration_cls.return_value.register.assert_called_once_with()
