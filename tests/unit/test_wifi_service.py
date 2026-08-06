from unittest.mock import MagicMock

import pytest

from app.services.wifi import WiFiService


def test_connect_returns_true_when_already_connected(mocker):
    mock_wlan_cls = mocker.patch("network.WLAN")
    mock_wlan = mock_wlan_cls.return_value
    mock_wlan.isconnected.return_value = True

    service = WiFiService("ssid", "password")

    assert service.connect() is True
    mock_wlan.active.assert_not_called()


def test_connect_waits_until_connected(mocker):
    mock_wlan_cls = mocker.patch("network.WLAN")
    mock_wlan = mock_wlan_cls.return_value
    mock_wlan.isconnected.side_effect = [False, False, True]
    mock_wlan.ifconfig.return_value = ["10.0.0.5"]
    mocker.patch("time.sleep")
    mocker.patch("time.time", side_effect=[0, 1, 2])

    service = WiFiService("ssid", "password", connect_timeout_seconds=10)

    assert service.connect() is True
    mock_wlan.connect.assert_called_once_with("ssid", "password")


def test_connect_retries_with_exponential_backoff(mocker):
    mock_wlan_cls = mocker.patch("network.WLAN")
    mock_wlan = mock_wlan_cls.return_value
    # Top-level check, then two timed-out attempts, then a successful one.
    mock_wlan.isconnected.side_effect = [False, False, False, True]
    mock_wlan.ifconfig.return_value = ["10.0.0.5"]
    mock_sleep = mocker.patch("time.sleep")
    mocker.patch("time.time", side_effect=[0, 0, 0, 0, 0])

    service = WiFiService(
        "ssid",
        "password",
        connect_timeout_seconds=0,
        reconnect_delay_seconds=2,
        max_reconnect_delay_seconds=30,
    )

    assert service.connect() is True
    assert mock_sleep.call_args_list == [mocker.call(2), mocker.call(4)]


def test_connect_backoff_caps_at_max_delay(mocker):
    mock_wlan_cls = mocker.patch("network.WLAN")
    mock_wlan = mock_wlan_cls.return_value
    mock_wlan.isconnected.side_effect = [False, False, False, False, True]
    mock_wlan.ifconfig.return_value = ["10.0.0.5"]
    mock_sleep = mocker.patch("time.sleep")
    mocker.patch("time.time", side_effect=[0] * 8)

    service = WiFiService(
        "ssid",
        "password",
        connect_timeout_seconds=0,
        reconnect_delay_seconds=2,
        max_reconnect_delay_seconds=5,
    )

    assert service.connect() is True
    assert mock_sleep.call_args_list == [
        mocker.call(2),
        mocker.call(4),
        mocker.call(5),
    ]


def test_connect_feeds_watchdog_on_each_retry(mocker):
    mock_wlan_cls = mocker.patch("network.WLAN")
    mock_wlan = mock_wlan_cls.return_value
    mock_wlan.isconnected.side_effect = [False, False, False, True]
    mock_wlan.ifconfig.return_value = ["10.0.0.5"]
    mocker.patch("time.sleep")
    mocker.patch("time.time", side_effect=[0, 0, 0, 0, 0])
    watchdog = MagicMock()

    service = WiFiService(
        "ssid",
        "password",
        connect_timeout_seconds=0,
        watchdog_service=watchdog,
    )
    service.connect()

    assert watchdog.feed.call_count == 3


def test_connect_propagates_wlan_connect_exception(mocker):
    mock_wlan_cls = mocker.patch("network.WLAN")
    mock_wlan = mock_wlan_cls.return_value
    mock_wlan.isconnected.return_value = False
    mock_wlan.connect.side_effect = OSError("wifi internal error")

    service = WiFiService("ssid", "password")

    with pytest.raises(OSError, match="wifi internal error"):
        service.connect()


def test_is_connected_delegates_to_wlan(mocker):
    mock_wlan_cls = mocker.patch("network.WLAN")
    mock_wlan = mock_wlan_cls.return_value
    mock_wlan.isconnected.return_value = True

    service = WiFiService("ssid", "password")

    assert service.is_connected() is True


def test_ensure_connected_is_noop_when_already_connected(mocker):
    mock_wlan_cls = mocker.patch("network.WLAN")
    mock_wlan = mock_wlan_cls.return_value
    mock_wlan.isconnected.return_value = True

    service = WiFiService("ssid", "password")
    service.ensure_connected()

    mock_wlan.active.assert_not_called()


def test_ensure_connected_reconnects_when_dropped(mocker):
    mock_wlan_cls = mocker.patch("network.WLAN")
    mock_wlan = mock_wlan_cls.return_value
    mock_wlan.isconnected.side_effect = [False, False, True]
    mock_wlan.ifconfig.return_value = ["10.0.0.5"]
    mocker.patch("time.sleep")
    mocker.patch("time.time", side_effect=[0, 1])

    service = WiFiService("ssid", "password", connect_timeout_seconds=10)
    service.ensure_connected()

    mock_wlan.connect.assert_called_once_with("ssid", "password")
