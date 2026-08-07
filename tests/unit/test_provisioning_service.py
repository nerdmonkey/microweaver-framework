from unittest.mock import MagicMock

import pytest

from app.services.provisioning import ProvisioningService


def make_provisioning_service(mocker, **kwargs):
    mocker.patch("app.services.provisioning.network")
    mocker.patch("app.services.provisioning.socket")
    return ProvisioningService(**kwargs)


def test_start_configures_open_ap_when_no_password(mocker):
    mock_network = mocker.patch("app.services.provisioning.network")
    service = ProvisioningService(ap_ssid="Setup", ap_password="")

    service.start()

    service.ap.active.assert_called_once_with(True)
    service.ap.ifconfig.assert_called_once_with(
        ("192.168.4.1", "255.255.255.0", "192.168.4.1", "192.168.4.1")
    )
    service.ap.config.assert_called_once_with(
        essid="Setup", authmode=mock_network.AUTH_OPEN
    )


def test_start_configures_wpa2_ap_when_password_given(mocker):
    mock_network = mocker.patch("app.services.provisioning.network")
    service = ProvisioningService(ap_ssid="Setup", ap_password="supersecret")

    service.start()

    service.ap.config.assert_called_once_with(
        essid="Setup",
        password="supersecret",
        authmode=mock_network.AUTH_WPA_WPA2_PSK,
    )


def test_stop_closes_server_and_deactivates_ap(mocker):
    service = make_provisioning_service(mocker)
    service.server = MagicMock()
    server = service.server

    service.stop()

    server.close.assert_called_once_with()
    assert service.server is None
    service.ap.active.assert_called_once_with(False)


def test_stop_without_server_only_deactivates_ap(mocker):
    service = make_provisioning_service(mocker)

    service.stop()

    service.ap.active.assert_called_once_with(False)


def test_scan_networks_decodes_and_dedupes_ssids(mocker):
    mock_network = mocker.patch("app.services.provisioning.network")
    mock_network.WLAN.return_value.scan.return_value = [
        (b"NetworkA", b"", 1, -40, 3, 0),
        (b"NetworkB", b"", 6, -60, 3, 0),
        (b"", b"", 11, -70, 3, 0),
    ]
    service = ProvisioningService()

    result = service.scan_networks()

    assert result == ["NetworkA", "NetworkB"]


def test_scan_networks_keeps_str_ssids_as_is(mocker):
    mock_network = mocker.patch("app.services.provisioning.network")
    mock_network.WLAN.return_value.scan.return_value = [
        ("AlreadyStr", b"", 1, -40, 3, 0)
    ]
    service = ProvisioningService()

    result = service.scan_networks()

    assert result == ["AlreadyStr"]


def test_run_serves_form_then_saves_and_stops_on_disconnect(mocker):
    mock_network = mocker.patch("app.services.provisioning.network")
    mock_socket = mocker.patch("app.services.provisioning.socket")
    mock_network.WLAN.return_value.scan.return_value = []
    server = mock_socket.socket.return_value
    client = MagicMock()
    server.accept.side_effect = [
        (client, ("10.0.0.5", 5000)),
        RuntimeError("stop test"),
    ]
    client.recv.return_value = b"GET / HTTP/1.1\r\nHost: 192.168.4.1\r\n\r\n"

    service = ProvisioningService(port=8080)

    with pytest.raises(RuntimeError, match="stop test"):
        service.run()

    server.bind.assert_called_once_with(("0.0.0.0", 8080))
    server.listen.assert_called_once_with(1)
    client.send.assert_called_once()
    assert b"Microweaver WiFi Setup" in client.send.call_args[0][0]
    client.close.assert_called_once_with()
    server.close.assert_called_once_with()


def test_handle_request_saves_credentials_on_post_save(mocker):
    service = make_provisioning_service(mocker)
    setting = MagicMock()
    service.setting = setting
    client = MagicMock()
    client.recv.return_value = (
        b"POST /save HTTP/1.1\r\nHost: x\r\n\r\nssid=MyWifi&password=hunter%202"
    )

    service._handle_request(client)

    setting.save.assert_called_once_with(wifi_ssid="MyWifi", wifi_password="hunter 2")
    response = client.send.call_args[0][0]
    assert b"200 OK" in response
    assert b"Credentials saved" in response


def test_handle_request_rejects_missing_ssid_with_400(mocker):
    service = make_provisioning_service(mocker)
    client = MagicMock()
    client.recv.return_value = b"POST /save HTTP/1.1\r\nHost: x\r\n\r\npassword=secret"

    service._handle_request(client)

    response = client.send.call_args[0][0]
    assert b"400 Bad Request" in response
    assert b"ssid is required" in response


def test_handle_request_returns_500_on_unexpected_error(mocker):
    service = make_provisioning_service(mocker)
    client = MagicMock()
    client.recv.side_effect = OSError("boom")

    service._handle_request(client)

    response = client.send.call_args[0][0]
    assert b"500 Internal Server Error" in response
    client.close.assert_called_once_with()


def test_save_credentials_without_setting_does_not_raise(mocker):
    service = make_provisioning_service(mocker)
    service.setting = None

    service._save_credentials({"ssid": "NoSettingWifi"})


def test_save_credentials_strips_ssid_whitespace(mocker):
    service = make_provisioning_service(mocker)
    setting = MagicMock()
    service.setting = setting

    service._save_credentials({"ssid": "  Padded  ", "password": "pw"})

    setting.save.assert_called_once_with(wifi_ssid="Padded", wifi_password="pw")


def test_unquote_decodes_plus_and_percent_escapes(mocker):
    service = make_provisioning_service(mocker)

    assert service._unquote("hello+world%21") == "hello world!"


def test_unquote_leaves_trailing_percent_without_pair_untouched(mocker):
    service = make_provisioning_service(mocker)

    assert service._unquote("100%") == "100%"


def test_parse_form_skips_pairs_without_equals(mocker):
    service = make_provisioning_service(mocker)

    fields = service._parse_form(b"GET / HTTP/1.1\r\n\r\nssid=A&flag&password=B")

    assert fields == {"ssid": "A", "password": "B"}


def test_response_defaults_to_error_for_unknown_status(mocker):
    service = make_provisioning_service(mocker)

    response = service._response(599, "weird")

    assert b"599 Error" in response
