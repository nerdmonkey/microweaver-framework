from unittest.mock import MagicMock

from app.services.mqtt import MqttConnection


def make_wifi_service(connected=True):
    wifi = MagicMock()
    wifi.is_connected.return_value = connected
    return wifi


def test_connect_succeeds_on_first_try(mocker):
    mock_client_cls = mocker.patch("app.services.mqtt.MQTTClient")
    mock_client = mock_client_cls.return_value
    wifi = make_wifi_service(connected=True)

    connection = MqttConnection("client", "broker", 1883, wifi)
    result = connection.connect()

    assert result is mock_client
    mock_client.connect.assert_called_once_with()
    wifi.connect.assert_not_called()


def test_connect_ensures_wifi_before_connecting(mocker):
    mocker.patch("app.services.mqtt.MQTTClient")
    wifi = make_wifi_service(connected=False)

    connection = MqttConnection("client", "broker", 1883, wifi)
    connection.connect()

    wifi.connect.assert_called_once_with()


def test_connect_retries_with_exponential_backoff(mocker):
    mock_client_cls = mocker.patch("app.services.mqtt.MQTTClient")
    failing_client = MagicMock()
    failing_client.connect.side_effect = OSError("refused")
    succeeding_client = MagicMock()
    mock_client_cls.side_effect = [failing_client, failing_client, succeeding_client]
    mock_sleep = mocker.patch("time.sleep")
    wifi = make_wifi_service(connected=True)

    connection = MqttConnection(
        "client",
        "broker",
        1883,
        wifi,
        reconnect_delay_seconds=2,
        max_reconnect_delay_seconds=30,
    )
    result = connection.connect()

    assert result is succeeding_client
    assert mock_sleep.call_args_list == [mocker.call(2), mocker.call(4)]


def test_connect_reacquires_wifi_after_it_drops_mid_retry(mocker):
    mock_client_cls = mocker.patch("app.services.mqtt.MQTTClient")
    failing_client = MagicMock()
    failing_client.connect.side_effect = OSError("refused")
    succeeding_client = MagicMock()
    mock_client_cls.side_effect = [failing_client, succeeding_client]
    mocker.patch("time.sleep")
    wifi = make_wifi_service(connected=True)
    # Wifi is up for the initial check, then found dropped after the first
    # failed MQTT attempt, requiring a reconnect before the retry succeeds.
    wifi.is_connected.side_effect = [True, False]

    connection = MqttConnection("client", "broker", 1883, wifi)
    result = connection.connect()

    assert result is succeeding_client
    assert wifi.connect.call_count == 1


def test_connect_backoff_caps_at_max_delay(mocker):
    mock_client_cls = mocker.patch("app.services.mqtt.MQTTClient")
    failing_client = MagicMock()
    failing_client.connect.side_effect = OSError("refused")
    succeeding_client = MagicMock()
    mock_client_cls.side_effect = [
        failing_client,
        failing_client,
        failing_client,
        succeeding_client,
    ]
    mock_sleep = mocker.patch("time.sleep")
    wifi = make_wifi_service(connected=True)

    connection = MqttConnection(
        "client",
        "broker",
        1883,
        wifi,
        reconnect_delay_seconds=2,
        max_reconnect_delay_seconds=5,
    )
    result = connection.connect()

    assert result is succeeding_client
    assert mock_sleep.call_args_list == [
        mocker.call(2),
        mocker.call(4),
        mocker.call(5),
    ]


def test_disconnect_clears_client():
    wifi = make_wifi_service(connected=True)
    connection = MqttConnection("client", "broker", 1883, wifi)
    connection.client = MagicMock()
    client = connection.client

    connection.disconnect()

    client.disconnect.assert_called_once_with()
    assert connection.client is None


def test_disconnect_without_active_client_is_noop():
    wifi = make_wifi_service(connected=True)
    connection = MqttConnection("client", "broker", 1883, wifi)

    connection.disconnect()


def test_disconnect_survives_client_exception():
    wifi = make_wifi_service(connected=True)
    connection = MqttConnection("client", "broker", 1883, wifi)
    connection.client = MagicMock()
    connection.client.disconnect.side_effect = OSError("already dropped")

    connection.disconnect()

    assert connection.client is None
