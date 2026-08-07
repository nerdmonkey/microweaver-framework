import main


def test_start_wires_and_runs_publish_service(mocker):
    mocker.patch("main.setting.DHT22_PIN", 15)
    mocker.patch("main.setting.RELAY_PIN", 16)
    mock_dht22_cls = mocker.patch("main.DHT22Adapter")
    mock_relay_cls = mocker.patch("main.RelayAdapter")
    mock_publish_cls = mocker.patch("main.PublishService")
    mock_instance = mock_publish_cls.return_value

    main.start()

    mock_dht22_cls.assert_called_once_with(pin=15)
    mock_relay_cls.assert_called_once_with(pin=16)
    mock_publish_cls.assert_called_once_with(
        adapters=[
            ("dht22", mock_dht22_cls.return_value),
            ("relay", mock_relay_cls.return_value),
        ]
    )
    mock_instance.run.assert_called_once_with()


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
    mock_provisioning_cls = mocker.patch("main.ProvisioningService")
    mock_instance = mock_provisioning_cls.return_value

    main.start_provisioning()

    mock_provisioning_cls.assert_called_once_with(
        ap_ssid="Microweaver-Setup",
        ap_password="secret123",
        ap_ip="192.168.4.1",
        port=80,
        setting=main.setting,
    )
    mock_instance.run.assert_called_once_with()


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
