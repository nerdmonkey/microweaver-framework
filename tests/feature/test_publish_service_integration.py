from unittest.mock import MagicMock

import pytest

from app.services.publish import PublishService


def _use_neutral_settings(mocker):
    mocker.patch("app.services.publish.setting.MQTT_BROKER", "broker")
    mocker.patch("app.services.publish.setting.MQTT_PORT", 1883)
    mocker.patch("app.services.publish.setting.MQTT_CLIENT_ID", "client")
    mocker.patch("app.services.publish.setting.MQTT_USERNAME", "")
    mocker.patch("app.services.publish.setting.MQTT_PASSWORD", "")
    mocker.patch("app.services.publish.setting.WIFI_SSID", "ssid")
    mocker.patch("app.services.publish.setting.WIFI_PASSWORD", "password")


def test_run_wires_real_wifi_and_mqtt_end_to_end(mocker):
    _use_neutral_settings(mocker)
    mocker.patch("network.WLAN").return_value.isconnected.return_value = True
    mock_client_cls = mocker.patch("app.services.mqtt.MQTTClient")
    good_client = MagicMock()
    mock_client_cls.side_effect = [good_client, KeyboardInterrupt("stop test")]
    mocker.patch("time.sleep", side_effect=ConnectionResetError("dropped"))

    service = PublishService()

    with pytest.raises(KeyboardInterrupt):
        service.run(message="hi")

    mock_client_cls.assert_any_call("client", "broker", 1883, keepalive=300)
    good_client.connect.assert_called_once_with()
    good_client.publish.assert_called_once_with(
        service.topics_pub[0], b"hi", qos=0, retain=False
    )


def test_run_recovers_from_real_wifi_drop_mid_loop(mocker):
    _use_neutral_settings(mocker)
    mock_wlan = mocker.patch("network.WLAN").return_value
    mock_wlan.isconnected.side_effect = [True, False, False, False, True, True]
    mock_wlan.ifconfig.return_value = ["10.0.0.5"]
    mock_client_cls = mocker.patch("app.services.mqtt.MQTTClient")
    good_client = MagicMock()
    mock_client_cls.side_effect = [good_client, KeyboardInterrupt("stop test")]
    mocker.patch("time.sleep", side_effect=[None, ConnectionResetError("dropped")])
    mocker.patch("time.time", return_value=0)

    service = PublishService()

    with pytest.raises(KeyboardInterrupt):
        service.run(message="hi")

    mock_wlan.disconnect.assert_called_once_with()
    mock_wlan.connect.assert_called_once_with("ssid", "password")
    good_client.publish.assert_called_once_with(
        service.topics_pub[0], b"hi", qos=0, retain=False
    )


def test_run_recovers_from_real_mqtt_broker_unreachable(mocker):
    _use_neutral_settings(mocker)
    mocker.patch("network.WLAN").return_value.isconnected.return_value = True
    mock_client_cls = mocker.patch("app.services.mqtt.MQTTClient")
    failing_client = MagicMock()
    failing_client.connect.side_effect = OSError("refused")
    succeeding_client = MagicMock()
    mock_client_cls.side_effect = [
        failing_client,
        succeeding_client,
        KeyboardInterrupt("stop test"),
    ]
    mock_sleep = mocker.patch(
        "time.sleep", side_effect=[None, ConnectionResetError("dropped")]
    )

    service = PublishService()

    with pytest.raises(KeyboardInterrupt):
        service.run(message="hi")

    assert mock_sleep.call_args_list[0] == mocker.call(2)
    succeeding_client.publish.assert_called_once_with(
        service.topics_pub[0], b"hi", qos=0, retain=False
    )


def test_run_feeds_real_watchdog_through_wifi_reconnect(mocker):
    _use_neutral_settings(mocker)
    mocker.patch("app.services.publish.setting.WATCHDOG_ENABLED", True)
    mock_wdt_cls = mocker.patch("app.services.watchdog.WDT")
    mock_wdt = mock_wdt_cls.return_value
    mock_wlan = mocker.patch("network.WLAN").return_value
    mock_wlan.isconnected.side_effect = [True, False, False, False, True, True]
    mock_wlan.ifconfig.return_value = ["10.0.0.5"]
    mock_client_cls = mocker.patch("app.services.mqtt.MQTTClient")
    good_client = MagicMock()
    mock_client_cls.side_effect = [good_client, KeyboardInterrupt("stop test")]
    mocker.patch("time.sleep", side_effect=[None, ConnectionResetError("dropped")])
    mocker.patch("time.time", return_value=0)

    service = PublishService()

    with pytest.raises(KeyboardInterrupt):
        service.run(message="hi")

    assert mock_wdt.feed.call_count >= 1
