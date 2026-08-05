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


def test_connect_times_out(mocker):
    mock_wlan_cls = mocker.patch("network.WLAN")
    mock_wlan = mock_wlan_cls.return_value
    mock_wlan.isconnected.return_value = False
    mocker.patch("time.sleep")
    mocker.patch("time.time", side_effect=[0, 1, 2])

    service = WiFiService("ssid", "password", connect_timeout_seconds=2)

    assert service.connect() is False


def test_is_connected_delegates_to_wlan(mocker):
    mock_wlan_cls = mocker.patch("network.WLAN")
    mock_wlan = mock_wlan_cls.return_value
    mock_wlan.isconnected.return_value = True

    service = WiFiService("ssid", "password")

    assert service.is_connected() is True
