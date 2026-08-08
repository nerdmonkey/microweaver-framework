from unittest.mock import MagicMock

import pytest

from app.services.mqtt import MqttConnection, MqttConnectionRejected, MQTTException


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


def test_connect_feeds_watchdog_on_each_retry(mocker):
    mock_client_cls = mocker.patch("app.services.mqtt.MQTTClient")
    failing_client = MagicMock()
    failing_client.connect.side_effect = OSError("refused")
    succeeding_client = MagicMock()
    mock_client_cls.side_effect = [failing_client, failing_client, succeeding_client]
    mocker.patch("time.sleep")
    wifi = make_wifi_service(connected=True)
    watchdog = MagicMock()

    connection = MqttConnection(
        "client", "broker", 1883, wifi, watchdog_service=watchdog
    )
    connection.connect()

    assert watchdog.feed.call_count == 3


def test_connect_passes_credentials_when_username_set(mocker):
    mock_client_cls = mocker.patch("app.services.mqtt.MQTTClient")
    wifi = make_wifi_service(connected=True)

    connection = MqttConnection(
        "client", "broker", 1883, wifi, username="alice", password="secret"
    )
    connection.connect()

    mock_client_cls.assert_called_once_with(
        "client", "broker", 1883, keepalive=300, user="alice", password="secret"
    )


def test_connect_omits_credentials_when_username_not_set():
    wifi = make_wifi_service(connected=True)

    connection = MqttConnection("client", "broker", 1883, wifi)

    assert connection.username is None
    assert connection.password is None


def test_connect_omits_credentials_when_username_empty(mocker):
    mock_client_cls = mocker.patch("app.services.mqtt.MQTTClient")
    wifi = make_wifi_service(connected=True)

    connection = MqttConnection(
        "client", "broker", 1883, wifi, username="", password=""
    )
    connection.connect()

    mock_client_cls.assert_called_once_with("client", "broker", 1883, keepalive=300)


def test_connect_passes_ssl_flag_when_enabled(mocker):
    mock_client_cls = mocker.patch("app.services.mqtt.MQTTClient")
    wifi = make_wifi_service(connected=True)

    connection = MqttConnection("client", "broker", 1883, wifi, ssl=True)
    connection.connect()

    mock_client_cls.assert_called_once_with(
        "client", "broker", 1883, keepalive=300, ssl=True
    )


def test_connect_passes_ssl_params_when_provided(mocker):
    mock_client_cls = mocker.patch("app.services.mqtt.MQTTClient")
    wifi = make_wifi_service(connected=True)
    ssl_params = {"cert": "/certs/client.crt", "key": "/certs/client.key"}

    connection = MqttConnection(
        "client", "broker", 1883, wifi, ssl=True, ssl_params=ssl_params
    )
    connection.connect()

    mock_client_cls.assert_called_once_with(
        "client", "broker", 1883, keepalive=300, ssl=True, ssl_params=ssl_params
    )


def test_connect_omits_ssl_when_disabled(mocker):
    mock_client_cls = mocker.patch("app.services.mqtt.MQTTClient")
    wifi = make_wifi_service(connected=True)

    connection = MqttConnection(
        "client", "broker", 1883, wifi, ssl_params={"cert": "/certs/client.crt"}
    )
    connection.connect()

    mock_client_cls.assert_called_once_with("client", "broker", 1883, keepalive=300)


def test_connect_sets_last_will_when_configured(mocker):
    mock_client_cls = mocker.patch("app.services.mqtt.MQTTClient")
    mock_client = mock_client_cls.return_value
    wifi = make_wifi_service(connected=True)

    connection = MqttConnection(
        "client",
        "broker",
        1883,
        wifi,
        lwt_topic="device/status",
        lwt_message="offline",
        lwt_retain=True,
        lwt_qos=1,
    )
    connection.connect()

    mock_client.set_last_will.assert_called_once_with(
        "device/status", "offline", retain=True, qos=1
    )
    mock_client.connect.assert_called_once_with()


def test_connect_omits_last_will_when_not_configured(mocker):
    mock_client_cls = mocker.patch("app.services.mqtt.MQTTClient")
    mock_client = mock_client_cls.return_value
    wifi = make_wifi_service(connected=True)

    connection = MqttConnection("client", "broker", 1883, wifi)
    connection.connect()

    mock_client.set_last_will.assert_not_called()


@pytest.mark.parametrize(
    "rc,reason",
    [
        (1, "unacceptable_protocol_version"),
        (2, "client_identifier_rejected"),
        (4, "bad_username_or_password"),
        (5, "not_authorized"),
    ],
)
def test_connect_raises_without_retrying_on_permanent_connack_rejection(
    mocker, rc, reason
):
    # rc 1/2/4/5 mean the broker has permanently rejected this client's
    # config/credentials - retrying with the same config every few seconds
    # can never succeed and only hammers the broker, so connect() should
    # surface it immediately instead of looping.
    mock_client_cls = mocker.patch("app.services.mqtt.MQTTClient")
    denied_client = MagicMock()
    denied_client.connect.side_effect = MQTTException(rc)
    mock_client_cls.return_value = denied_client
    mock_sleep = mocker.patch("time.sleep")
    wifi = make_wifi_service(connected=True)

    connection = MqttConnection("client", "broker", 1883, wifi)

    with pytest.raises(MqttConnectionRejected) as excinfo:
        connection.connect()

    assert excinfo.value.rc == rc
    assert excinfo.value.reason == reason
    mock_sleep.assert_not_called()
    assert mock_client_cls.call_count == 1


def test_connect_retries_with_backoff_on_transient_connack_rejection(mocker):
    # rc=3 ("server unavailable") is the broker itself being down/overloaded
    # rather than a rejection of this client - that can recover on its own,
    # so it keeps the normal exponential-backoff retry loop.
    mock_client_cls = mocker.patch("app.services.mqtt.MQTTClient")
    unavailable_client = MagicMock()
    unavailable_client.connect.side_effect = MQTTException(3)
    allowed_client = MagicMock()
    mock_client_cls.side_effect = [unavailable_client, allowed_client]
    mock_sleep = mocker.patch("time.sleep")
    wifi = make_wifi_service(connected=True)

    connection = MqttConnection(
        "client", "broker", 1883, wifi, reconnect_delay_seconds=2
    )
    result = connection.connect()

    assert result is allowed_client
    mock_sleep.assert_called_once_with(2)


def test_connect_treats_unrecognized_connack_rc_as_transient(mocker):
    mock_client_cls = mocker.patch("app.services.mqtt.MQTTClient")
    odd_client = MagicMock()
    odd_client.connect.side_effect = MQTTException(99)
    allowed_client = MagicMock()
    mock_client_cls.side_effect = [odd_client, allowed_client]
    mock_sleep = mocker.patch("time.sleep")
    wifi = make_wifi_service(connected=True)

    connection = MqttConnection(
        "client", "broker", 1883, wifi, reconnect_delay_seconds=2
    )
    result = connection.connect()

    assert result is allowed_client
    mock_sleep.assert_called_once_with(2)


def test_connect_treats_connack_exception_with_no_rc_as_transient(mocker):
    mock_client_cls = mocker.patch("app.services.mqtt.MQTTClient")
    blank_client = MagicMock()
    blank_client.connect.side_effect = MQTTException()
    allowed_client = MagicMock()
    mock_client_cls.side_effect = [blank_client, allowed_client]
    mock_sleep = mocker.patch("time.sleep")
    wifi = make_wifi_service(connected=True)

    connection = MqttConnection(
        "client", "broker", 1883, wifi, reconnect_delay_seconds=2
    )
    result = connection.connect()

    assert result is allowed_client
    mock_sleep.assert_called_once_with(2)


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
