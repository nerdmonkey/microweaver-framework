from unittest.mock import MagicMock

from app.services.safe_mode import SafeModeService, setting


def test_run_prints_message_and_sleeps_forever(mocker, capsys):
    sleep_mock = mocker.patch(
        "time.sleep", side_effect=[None, None, RuntimeError("stop test")]
    )
    service = SafeModeService(sleep_seconds=3)

    try:
        service.run()
    except RuntimeError:
        pass

    assert sleep_mock.call_args_list == [
        mocker.call(3),
        mocker.call(3),
        mocker.call(3),
    ]
    out = capsys.readouterr().out
    assert "SAFE MODE" in out


def test_run_uses_default_sleep_seconds(mocker):
    sleep_mock = mocker.patch("time.sleep", side_effect=RuntimeError("stop test"))
    service = SafeModeService()

    try:
        service.run()
    except RuntimeError:
        pass

    sleep_mock.assert_called_once_with(5)


def _enable_recovery(mocker):
    mocker.patch("app.services.safe_mode.setting.WIFI_SSID", "TestNet")
    mocker.patch("app.services.safe_mode.setting.MQTT_ENABLED", True)
    mocker.patch("app.services.safe_mode.setting.OTA_ENABLED", True)
    mocker.patch("app.services.safe_mode.setting.OTA_TOPIC", "ota/update")


def test_init_skips_recovery_wiring_when_wifi_not_configured(mocker):
    mocker.patch("app.services.safe_mode.setting.WIFI_SSID", "")
    mocker.patch("app.services.safe_mode.setting.MQTT_ENABLED", True)
    mocker.patch("app.services.safe_mode.setting.OTA_ENABLED", True)
    mock_wifi_cls = mocker.patch("app.services.safe_mode.WiFiService")

    service = SafeModeService()

    mock_wifi_cls.assert_not_called()
    assert service.wifi_service is None


def test_init_skips_recovery_wiring_when_mqtt_disabled(mocker):
    mocker.patch("app.services.safe_mode.setting.WIFI_SSID", "TestNet")
    mocker.patch("app.services.safe_mode.setting.MQTT_ENABLED", False)
    mocker.patch("app.services.safe_mode.setting.OTA_ENABLED", True)
    mock_wifi_cls = mocker.patch("app.services.safe_mode.WiFiService")

    service = SafeModeService()

    mock_wifi_cls.assert_not_called()
    assert service.wifi_service is None


def test_init_skips_recovery_wiring_when_ota_disabled(mocker):
    mocker.patch("app.services.safe_mode.setting.WIFI_SSID", "TestNet")
    mocker.patch("app.services.safe_mode.setting.MQTT_ENABLED", True)
    mocker.patch("app.services.safe_mode.setting.OTA_ENABLED", False)
    mock_wifi_cls = mocker.patch("app.services.safe_mode.WiFiService")

    service = SafeModeService()

    mock_wifi_cls.assert_not_called()
    assert service.wifi_service is None


def test_init_wires_recovery_services_when_fully_configured(mocker):
    _enable_recovery(mocker)
    mock_wifi_cls = mocker.patch("app.services.safe_mode.WiFiService")
    mock_connection_cls = mocker.patch("app.services.safe_mode.MqttConnection")
    mock_ota_cls = mocker.patch("app.services.safe_mode.OtaService")

    service = SafeModeService()

    mock_wifi_cls.assert_called_once_with(
        setting.WIFI_SSID,
        setting.WIFI_PASSWORD,
        setting.WIFI_CONNECT_TIMEOUT_SECONDS,
        setting.WIFI_RECONNECT_DELAY_SECONDS,
        setting.WIFI_MAX_RECONNECT_DELAY_SECONDS,
    )
    mock_connection_cls.assert_called_once_with(
        setting.MQTT_CLIENT_ID,
        setting.MQTT_BROKER,
        setting.MQTT_PORT,
        mock_wifi_cls.return_value,
        setting.MQTT_RECONNECT_DELAY_SECONDS,
        setting.MQTT_MAX_RECONNECT_DELAY_SECONDS,
        setting.MQTT_KEEPALIVE_SECONDS,
        username=setting.MQTT_USERNAME,
        password=setting.MQTT_PASSWORD,
    )
    mock_ota_cls.assert_called_once_with(
        setting.OTA_MANIFEST_URL,
        setting=setting,
        state_path=setting.OTA_STATE_PATH,
    )
    assert service.wifi_service is mock_wifi_cls.return_value
    assert service.connection is mock_connection_cls.return_value
    assert service.ota_service is mock_ota_cls.return_value


def test_run_listens_for_ota_message_and_polls(mocker, capsys):
    _enable_recovery(mocker)
    mocker.patch("app.services.safe_mode.WiFiService")
    mock_connection_cls = mocker.patch("app.services.safe_mode.MqttConnection")
    mock_connection = mock_connection_cls.return_value
    mocker.patch("app.services.safe_mode.OtaService")
    mock_client = MagicMock()
    mock_client.check_msg.side_effect = [None, None, OSError("dropped")]
    mock_connection.connect.side_effect = [mock_client, RuntimeError("stop test")]
    mocker.patch("time.sleep")

    service = SafeModeService(sleep_seconds=3)

    try:
        service.run()
    except RuntimeError:
        pass

    mock_client.set_callback.assert_called_once_with(service._on_message)
    mock_client.subscribe.assert_called_once_with("ota/update")
    assert mock_client.check_msg.call_count == 3
    mock_connection.disconnect.assert_called_once_with()
    out = capsys.readouterr().out
    assert "listening for OTA update" in out


def test_run_reconnects_after_recovery_listener_drops(mocker):
    _enable_recovery(mocker)
    mocker.patch("app.services.safe_mode.WiFiService")
    mock_connection_cls = mocker.patch("app.services.safe_mode.MqttConnection")
    mock_connection = mock_connection_cls.return_value
    mocker.patch("app.services.safe_mode.OtaService")
    client_a, client_b = MagicMock(), MagicMock()
    client_a.check_msg.side_effect = OSError("dropped")
    client_b.check_msg.side_effect = ConnectionResetError("dropped again")
    mock_connection.connect.side_effect = [
        client_a,
        client_b,
        RuntimeError("stop test"),
    ]
    mocker.patch("time.sleep")

    service = SafeModeService()

    try:
        service.run()
    except RuntimeError:
        pass

    assert mock_connection.connect.call_count == 3
    assert mock_connection.disconnect.call_count == 2


def test_on_message_applies_update_and_resets_on_success(mocker, capsys):
    _enable_recovery(mocker)
    mocker.patch("app.services.safe_mode.WiFiService")
    mocker.patch("app.services.safe_mode.MqttConnection")
    mock_ota_cls = mocker.patch("app.services.safe_mode.OtaService")
    mock_ota = mock_ota_cls.return_value
    mock_ota.apply_update.return_value = True
    mock_reset = mocker.patch("app.services.safe_mode.machine.reset")

    service = SafeModeService()
    service._on_message(b"ota/update", b"update now")

    mock_ota.apply_update.assert_called_once_with()
    mock_reset.assert_called_once_with()
    out = capsys.readouterr().out
    assert "OTA update triggered" in out
    assert "update applied, restarting" in out


def test_on_message_skips_reset_when_no_update_applied(mocker):
    _enable_recovery(mocker)
    mocker.patch("app.services.safe_mode.WiFiService")
    mocker.patch("app.services.safe_mode.MqttConnection")
    mock_ota_cls = mocker.patch("app.services.safe_mode.OtaService")
    mock_ota_cls.return_value.apply_update.return_value = False
    mock_reset = mocker.patch("app.services.safe_mode.machine.reset")

    service = SafeModeService()
    service._on_message(b"ota/update", b"update now")

    mock_reset.assert_not_called()


def test_on_message_survives_apply_update_exception(mocker, capsys):
    _enable_recovery(mocker)
    mocker.patch("app.services.safe_mode.WiFiService")
    mocker.patch("app.services.safe_mode.MqttConnection")
    mock_ota_cls = mocker.patch("app.services.safe_mode.OtaService")
    mock_ota_cls.return_value.apply_update.side_effect = RuntimeError("boom")
    mock_reset = mocker.patch("app.services.safe_mode.machine.reset")

    service = SafeModeService()
    service._on_message(b"ota/update", b"update now")

    mock_reset.assert_not_called()
    out = capsys.readouterr().out
    assert "OTA update failed" in out
