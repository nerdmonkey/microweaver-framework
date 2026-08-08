import json
from unittest.mock import MagicMock

import pytest

from app.services.provisioning import ProvisioningService
from config.app import Setting


def _config_path(tmp_path):
    return str(tmp_path / "device_config.json")


def test_save_credentials_persists_to_disk_and_reloads(mocker, tmp_path):
    mock_network = mocker.patch("app.services.provisioning.network")
    mocker.patch("app.services.provisioning.socket")
    mock_network.WLAN.return_value.isconnected.return_value = True
    config_path = _config_path(tmp_path)
    real_setting = Setting(config_path=config_path)
    service = ProvisioningService(setting=real_setting)
    client = MagicMock()
    client.recv.return_value = (
        b"POST /save HTTP/1.1\r\nHost: x\r\n\r\n"
        b"ssid=MyWifi&password=hunter2&claim_code=ABC123"
    )

    service._handle_request(client)

    response = client.send.call_args[0][0]
    assert b"200 OK" in response
    assert b"Connected!" in response
    with open(config_path) as config_file:
        assert json.load(config_file) == {
            "wifi_ssid": "MyWifi",
            "wifi_password": "hunter2",
            "claim_code": "ABC123",
        }

    reloaded = Setting(config_path=config_path).get_settings()
    assert reloaded.WIFI_SSID == "MyWifi"
    assert reloaded.WIFI_PASSWORD == "hunter2"
    assert reloaded.CLAIM_CODE == "ABC123"


def test_save_credentials_persists_even_when_real_wifi_test_times_out(mocker, tmp_path):
    mock_network = mocker.patch("app.services.provisioning.network")
    mocker.patch("app.services.provisioning.socket")
    mock_network.WLAN.return_value.isconnected.return_value = False
    mocker.patch("time.sleep")
    mocker.patch("time.time", side_effect=[0, 999])
    config_path = _config_path(tmp_path)
    real_setting = Setting(config_path=config_path)
    service = ProvisioningService(setting=real_setting, wifi_test_timeout_seconds=20)
    client = MagicMock()
    client.recv.return_value = (
        b"POST /save HTTP/1.1\r\nHost: x\r\n\r\nssid=BadWifi&password=wrong"
    )

    service._handle_request(client)

    response = client.send.call_args[0][0]
    assert b"200 OK" in response
    assert b"could not connect" in response
    with open(config_path) as config_file:
        saved = json.load(config_file)
    assert saved["wifi_ssid"] == "BadWifi"
    assert saved["wifi_password"] == "wrong"


def test_missing_ssid_rejected_without_touching_real_config_file(mocker, tmp_path):
    mocker.patch("app.services.provisioning.network")
    mocker.patch("app.services.provisioning.socket")
    config_path = _config_path(tmp_path)
    real_setting = Setting(config_path=config_path)
    service = ProvisioningService(setting=real_setting)
    client = MagicMock()
    client.recv.return_value = b"POST /save HTTP/1.1\r\nHost: x\r\n\r\nssid=&password=x"

    service._handle_request(client)

    response = client.send.call_args[0][0]
    assert b"400 Bad Request" in response
    assert b"ssid is required" in response
    assert not (tmp_path / "device_config.json").exists()


def test_run_saves_real_credentials_through_full_accept_loop(mocker, tmp_path):
    mock_network = mocker.patch("app.services.provisioning.network")
    mock_socket = mocker.patch("app.services.provisioning.socket")
    mock_network.WLAN.return_value.scan.return_value = []
    mock_network.WLAN.return_value.isconnected.return_value = True
    mocker.patch("time.sleep")
    mocker.patch("time.time", side_effect=[0, 0])
    server = mock_socket.socket.return_value
    client = MagicMock()
    client.recv.return_value = (
        b"POST /save HTTP/1.1\r\nHost: x\r\n\r\nssid=RealRun&password=secret123"
    )
    server.accept.side_effect = [
        (client, ("10.0.0.5", 1234)),
        RuntimeError("stop test"),
    ]
    config_path = _config_path(tmp_path)
    real_setting = Setting(config_path=config_path)
    service = ProvisioningService(port=8080, setting=real_setting)

    with pytest.raises(RuntimeError, match="stop test"):
        service.run()

    server.close.assert_called_once_with()
    with open(config_path) as config_file:
        assert json.load(config_file) == {
            "wifi_ssid": "RealRun",
            "wifi_password": "secret123",
        }
