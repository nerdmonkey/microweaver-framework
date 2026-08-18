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
    )
    mock_runtime_cls.return_value.run.assert_called_once_with()


def test_start_wires_and_runs_runtime_service_with_dht11(mocker):
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
    )
    mock_runtime_cls.return_value.run.assert_called_once_with()


def test_start_uses_custom_dht_topic_suffixes(mocker):
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
    )


def test_start_skips_dht_adapter_when_disabled(mocker):
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
    )


def test_start_skips_relay_adapter_when_disabled(mocker):
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
    )


def test_start_wires_no_adapters_when_all_disabled(mocker):
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
    )


def test_start_wires_rgb_adapter_when_enabled(mocker):
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
    )


def test_start_skips_rgb_adapter_when_disabled(mocker):
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
    )


def test_start_wires_relay_and_rgb_together(mocker):
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
    )


def test_start_wires_oled_adapter_when_enabled(mocker):
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
    )


def test_start_skips_oled_adapter_when_disabled(mocker):
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
    )


def test_start_wires_relay_and_oled_together(mocker):
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
    )


def test_start_wires_potentiometer_adapter_when_enabled(mocker):
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
    )


def test_start_wires_rotary_angle_adapter_when_enabled(mocker):
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
    )


def test_start_skips_potentiometer_and_rotary_angle_when_disabled(mocker):
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
    )


def test_start_wires_potentiometer_and_rotary_angle_together_with_dht(mocker):
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
    )


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
