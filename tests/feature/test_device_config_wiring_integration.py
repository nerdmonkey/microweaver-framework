import json

from config.app import Setting


def _write_config(tmp_path, **overrides):
    config = {
        "wifi_ssid": "HomeNet",
        "wifi_password": "hunter2",
        "wifi_ip": "192.168.1.50",
        "wifi_subnet": "255.255.255.0",
        "wifi_gateway": "192.168.1.1",
        "wifi_dns": "8.8.8.8",
        "wifi_disable_power_save": True,
        "mqtt_broker": "mqtt.example.com",
        "mqtt_port": 8883,
        "mqtt_client_id": "device-1",
        "mqtt_username": "alice",
        "mqtt_password": "s3cret",
        "mqtt_ssl": True,
        "mqtt_ssl_cert_path": "/certs/client.crt",
        "mqtt_ssl_key_path": "/certs/client.key",
        "mqtt_lwt_topic": "device/status",
        "mqtt_lwt_message": "offline",
        "mqtt_lwt_retain": True,
        "mqtt_lwt_qos": 1,
        "watchdog_enabled": True,
        "watchdog_timeout_ms": 5000,
    }
    config.update(overrides)
    config_path = tmp_path / "device_config.json"
    config_path.write_text(json.dumps(config))
    return Setting(config_path=str(config_path)).get_settings()


def test_publish_service_wires_static_ip_and_mqtt_from_real_json_file(mocker, tmp_path):
    real_settings = _write_config(tmp_path)
    mocker.patch("app.services.publish.setting", real_settings)
    mocker.patch("app.services.watchdog.WDT")

    from app.services.publish import PublishService

    service = PublishService()

    assert service.wifi_service.static_ip == (
        "192.168.1.50",
        "255.255.255.0",
        "192.168.1.1",
        "8.8.8.8",
    )
    assert service.wifi_service.disable_power_save is True
    assert service.wifi_service.ssid == "HomeNet"
    assert service.wifi_service.password == "hunter2"
    assert service.connection.broker == "mqtt.example.com"
    assert service.connection.port == 8883
    assert service.connection.client_id == "device-1"
    assert service.connection.username == "alice"
    assert service.connection.password == "s3cret"
    assert service.connection.ssl is True
    assert service.connection.ssl_params == {
        "cert": "/certs/client.crt",
        "key": "/certs/client.key",
    }
    assert service.connection.lwt_topic == "device/status"
    assert service.connection.lwt_message == "offline"
    assert service.connection.lwt_retain is True
    assert service.connection.lwt_qos == 1
    assert service.watchdog_service.timeout_ms == 5000


def test_subscribe_service_wires_static_ip_and_mqtt_from_real_json_file(
    mocker, tmp_path
):
    real_settings = _write_config(tmp_path)
    mocker.patch("app.services.subscribe.setting", real_settings)
    mocker.patch("app.services.watchdog.WDT")

    from app.services.subscribe import SubscribeService

    service = SubscribeService()

    assert service.wifi_service.static_ip == (
        "192.168.1.50",
        "255.255.255.0",
        "192.168.1.1",
        "8.8.8.8",
    )
    assert service.connection.broker == "mqtt.example.com"
    assert service.connection.ssl_params == {
        "cert": "/certs/client.crt",
        "key": "/certs/client.key",
    }
    assert service.watchdog_service.timeout_ms == 5000


def test_publish_service_skips_static_ip_when_json_leaves_it_blank(mocker, tmp_path):
    real_settings = _write_config(tmp_path, wifi_ip="", wifi_subnet="")
    mocker.patch("app.services.publish.setting", real_settings)

    from app.services.publish import PublishService

    service = PublishService()

    assert service.wifi_service.static_ip is None
