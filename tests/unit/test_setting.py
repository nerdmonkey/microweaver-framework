import json

import pytest

from config.app import ConfigError, Setting


def test_setting_reads_values_from_device_config(tmp_path):
    config_path = tmp_path / "device_config.json"
    config_path.write_text(
        json.dumps(
            {
                "app_environment": "test",
                "app_version": "1.2.3",
                "mqtt_enabled": False,
                "mqtt_broker": "test_broker",
                "mqtt_client_id": "test_id",
                "mqtt_port": 1884,
                "mqtt_topic_pub": "test/pub",
                "mqtt_topic_sub": "test/sub",
                "mqtt_username": "test_user",
                "mqtt_password": "test_pass",
                "wifi_ssid": "test_ssid",
                "wifi_password": "test_password",
                "wifi_ip": "192.168.1.50",
                "wifi_subnet": "255.255.255.0",
                "wifi_gateway": "192.168.1.1",
                "wifi_dns": "8.8.8.8",
                "wifi_disable_power_save": True,
                "wifi_connect_timeout_seconds": 5,
                "wifi_reconnect_delay_seconds": 3,
                "wifi_max_reconnect_delay_seconds": 20,
                "mqtt_reconnect_delay_seconds": 1,
                "mqtt_max_reconnect_delay_seconds": 10,
                "mqtt_keepalive_seconds": 60,
                "mqtt_ssl": True,
                "mqtt_ssl_cert_path": "/certs/client.crt",
                "mqtt_ssl_key_path": "/certs/client.key",
                "mqtt_lwt_topic": "device/status",
                "mqtt_lwt_message": "offline",
                "mqtt_lwt_retain": True,
                "mqtt_lwt_qos": 1,
                "mqtt_publish_retain": True,
                "mqtt_publish_qos": 1,
                "watchdog_enabled": True,
                "watchdog_timeout_ms": 5000,
                "boot_loop_protection_enabled": True,
                "boot_loop_max_attempts": 3,
                "boot_loop_state_path": "test_boot_state.json",
                "boot_interrupt_window_seconds": 4,
                "autostart_enabled": False,
                "safe_mode_sleep_seconds": 2,
                "memory_monitor_enabled": True,
                "memory_monitor_threshold_bytes": 20000,
                "memory_monitor_action": "warn",
                "health_check_enabled": True,
                "health_check_interval_seconds": 15,
                "health_report_enabled": True,
                "health_report_interval_seconds": 45,
                "health_report_topic": "test/device/health",
                "service_restart_enabled": True,
                "service_restart_max_attempts": 7,
                "log_format": "kv",
                "log_level": "debug",
                "dht22_pin": 21,
                "relay_pin": 22,
                "ota_enabled": True,
                "ota_manifest_url": "https://api.example.com/manifest.json",
                "ota_state_path": "test_ota_state.json",
                "ota_topic": "test/ota/update",
            }
        )
    )

    setting = Setting(config_path=str(config_path))

    assert setting.APP_ENVIRONMENT == "test"
    assert setting.APP_VERSION == "1.2.3"
    assert setting.MQTT_ENABLED is False
    assert setting.MQTT_BROKER == "test_broker"
    assert setting.MQTT_CLIENT_ID == "test_id"
    assert setting.MQTT_PORT == 1884
    assert setting.MQTT_TOPIC_PUB == "test/pub"
    assert setting.MQTT_TOPIC_SUB == ["test/sub"]
    assert setting.MQTT_USERNAME == "test_user"
    assert setting.MQTT_PASSWORD == "test_pass"
    assert setting.WIFI_SSID == "test_ssid"
    assert setting.WIFI_PASSWORD == "test_password"
    assert setting.WIFI_IP == "192.168.1.50"
    assert setting.WIFI_SUBNET == "255.255.255.0"
    assert setting.WIFI_GATEWAY == "192.168.1.1"
    assert setting.WIFI_DNS == "8.8.8.8"
    assert setting.WIFI_DISABLE_POWER_SAVE is True
    assert setting.WIFI_CONNECT_TIMEOUT_SECONDS == 5
    assert setting.WIFI_RECONNECT_DELAY_SECONDS == 3
    assert setting.WIFI_MAX_RECONNECT_DELAY_SECONDS == 20
    assert setting.MQTT_RECONNECT_DELAY_SECONDS == 1
    assert setting.MQTT_MAX_RECONNECT_DELAY_SECONDS == 10
    assert setting.MQTT_KEEPALIVE_SECONDS == 60
    assert setting.MQTT_SSL is True
    assert setting.MQTT_SSL_CERT_PATH == "/certs/client.crt"
    assert setting.MQTT_SSL_KEY_PATH == "/certs/client.key"
    assert setting.MQTT_LWT_TOPIC == "device/status"
    assert setting.MQTT_LWT_MESSAGE == "offline"
    assert setting.MQTT_LWT_RETAIN is True
    assert setting.MQTT_LWT_QOS == 1
    assert setting.MQTT_PUBLISH_RETAIN is True
    assert setting.MQTT_PUBLISH_QOS == 1
    assert setting.WATCHDOG_ENABLED is True
    assert setting.WATCHDOG_TIMEOUT_MS == 5000
    assert setting.BOOT_LOOP_PROTECTION_ENABLED is True
    assert setting.BOOT_LOOP_MAX_ATTEMPTS == 3
    assert setting.BOOT_LOOP_STATE_PATH == "test_boot_state.json"
    assert setting.BOOT_INTERRUPT_WINDOW_SECONDS == 4
    assert setting.AUTOSTART_ENABLED is False
    assert setting.SAFE_MODE_SLEEP_SECONDS == 2
    assert setting.MEMORY_MONITOR_ENABLED is True
    assert setting.MEMORY_MONITOR_THRESHOLD_BYTES == 20000
    assert setting.MEMORY_MONITOR_ACTION == "warn"
    assert setting.HEALTH_CHECK_ENABLED is True
    assert setting.HEALTH_CHECK_INTERVAL_SECONDS == 15
    assert setting.HEALTH_REPORT_ENABLED is True
    assert setting.HEALTH_REPORT_INTERVAL_SECONDS == 45
    assert setting.HEALTH_REPORT_TOPIC == "test/device/health"
    assert setting.SERVICE_RESTART_ENABLED is True
    assert setting.SERVICE_RESTART_MAX_ATTEMPTS == 7
    assert setting.LOG_FORMAT == "kv"
    assert setting.LOG_LEVEL == "debug"
    assert setting.DHT22_PIN == 21
    assert setting.RELAY_PIN == 22
    assert setting.OTA_ENABLED is True
    assert setting.OTA_MANIFEST_URL == "https://api.example.com/manifest.json"
    assert setting.OTA_STATE_PATH == "test_ota_state.json"
    assert setting.OTA_TOPIC == "test/ota/update"


def test_setting_falls_back_to_defaults_when_file_missing(tmp_path):
    missing_path = tmp_path / "does_not_exist.json"

    setting = Setting(config_path=str(missing_path))

    assert setting.APP_ENVIRONMENT == "local"
    assert setting.APP_VERSION == "0.1.0"
    assert setting.MQTT_ENABLED is True
    assert setting.MQTT_BROKER == "localhost"
    assert setting.MQTT_CLIENT_ID == "microweaver"
    assert setting.MQTT_PORT == 1883
    assert setting.MQTT_TOPIC_SUB == ["data/sensor/room/temperature"]
    assert setting.WIFI_SSID == ""
    assert setting.WIFI_PASSWORD == ""
    assert setting.WIFI_IP == ""
    assert setting.WIFI_SUBNET == ""
    assert setting.WIFI_GATEWAY == ""
    assert setting.WIFI_DNS == ""
    assert setting.WIFI_DISABLE_POWER_SAVE is False
    assert setting.WIFI_CONNECT_TIMEOUT_SECONDS == 20
    assert setting.WIFI_RECONNECT_DELAY_SECONDS == 2
    assert setting.WIFI_MAX_RECONNECT_DELAY_SECONDS == 30
    assert setting.MQTT_RECONNECT_DELAY_SECONDS == 2
    assert setting.MQTT_MAX_RECONNECT_DELAY_SECONDS == 30
    assert setting.MQTT_KEEPALIVE_SECONDS == 300
    assert setting.MQTT_SSL is False
    assert setting.MQTT_SSL_CERT_PATH == ""
    assert setting.MQTT_SSL_KEY_PATH == ""
    assert setting.MQTT_LWT_TOPIC == ""
    assert setting.MQTT_LWT_MESSAGE == ""
    assert setting.MQTT_LWT_RETAIN is False
    assert setting.MQTT_LWT_QOS == 0
    assert setting.MQTT_PUBLISH_RETAIN is False
    assert setting.MQTT_PUBLISH_QOS == 0
    assert setting.WATCHDOG_ENABLED is False
    assert setting.WATCHDOG_TIMEOUT_MS == 8000
    assert setting.BOOT_LOOP_PROTECTION_ENABLED is False
    assert setting.BOOT_LOOP_MAX_ATTEMPTS == 5
    assert setting.BOOT_LOOP_STATE_PATH == "boot_state.json"
    assert setting.BOOT_INTERRUPT_WINDOW_SECONDS == 2
    assert setting.AUTOSTART_ENABLED is True
    assert setting.SAFE_MODE_SLEEP_SECONDS == 5
    assert setting.MEMORY_MONITOR_ENABLED is False
    assert setting.MEMORY_MONITOR_THRESHOLD_BYTES == 10000
    assert setting.MEMORY_MONITOR_ACTION == "log"
    assert setting.HEALTH_CHECK_ENABLED is False
    assert setting.HEALTH_CHECK_INTERVAL_SECONDS == 30
    assert setting.HEALTH_REPORT_ENABLED is False
    assert setting.HEALTH_REPORT_INTERVAL_SECONDS == 60
    assert setting.HEALTH_REPORT_TOPIC == "device/microweaver/health"
    assert setting.SERVICE_RESTART_ENABLED is False
    assert setting.SERVICE_RESTART_MAX_ATTEMPTS == 3
    assert setting.LOG_FORMAT == "json"
    assert setting.LOG_LEVEL == "info"
    assert setting.DHT22_PIN == 4
    assert setting.RELAY_PIN == 5
    assert setting.CLAIM_ENABLED is False
    assert setting.CLAIM_URL == ""
    assert setting.CLAIM_CODE == ""
    assert setting.DEVICE_ID == ""
    assert setting.DEVICE_CERT == ""
    assert setting.DEVICE_KEY == ""
    assert setting.OTA_ENABLED is False
    assert setting.OTA_MANIFEST_URL == ""
    assert setting.OTA_STATE_PATH == "ota_state.json"
    assert setting.OTA_TOPIC == "ota/update"


def test_get_settings_method():
    setting = Setting()
    retrieved_settings = setting.get_settings()
    assert (
        retrieved_settings == setting
    ), "get_settings should return the Setting instance"


def test_setting_falls_back_to_defaults_when_json_is_unparseable(tmp_path):
    config_path = tmp_path / "device_config.json"
    config_path.write_text("{not valid json")

    setting = Setting(config_path=str(config_path))

    assert setting.APP_ENVIRONMENT == "local"
    assert setting.MQTT_PORT == 1883


def test_setting_raises_on_wrong_type_field(tmp_path):
    config_path = tmp_path / "device_config.json"
    config_path.write_text(json.dumps({"mqtt_port": "not_a_number"}))

    with pytest.raises(ConfigError, match="mqtt_port must be an integer"):
        Setting(config_path=str(config_path))


def test_setting_raises_on_int_field_above_max(tmp_path):
    config_path = tmp_path / "device_config.json"
    config_path.write_text(json.dumps({"mqtt_port": 70000}))

    with pytest.raises(ConfigError, match="mqtt_port must be <= 65535"):
        Setting(config_path=str(config_path))


def test_setting_raises_on_int_field_below_min(tmp_path):
    config_path = tmp_path / "device_config.json"
    config_path.write_text(json.dumps({"safe_mode_sleep_seconds": -1}))

    with pytest.raises(ConfigError, match="safe_mode_sleep_seconds must be >= 0"):
        Setting(config_path=str(config_path))


def test_setting_raises_on_non_boolean_field(tmp_path):
    config_path = tmp_path / "device_config.json"
    config_path.write_text(json.dumps({"watchdog_enabled": "yes"}))

    with pytest.raises(ConfigError, match="watchdog_enabled must be a boolean"):
        Setting(config_path=str(config_path))


def test_setting_raises_on_invalid_choice_field(tmp_path):
    config_path = tmp_path / "device_config.json"
    config_path.write_text(json.dumps({"log_format": "xml"}))

    with pytest.raises(ConfigError, match="log_format must be one of"):
        Setting(config_path=str(config_path))


def test_setting_raises_on_invalid_log_level(tmp_path):
    config_path = tmp_path / "device_config.json"
    config_path.write_text(json.dumps({"log_level": "verbose"}))

    with pytest.raises(ConfigError, match="log_level must be one of"):
        Setting(config_path=str(config_path))


def test_setting_raises_on_non_string_field(tmp_path):
    config_path = tmp_path / "device_config.json"
    config_path.write_text(json.dumps({"mqtt_broker": 12345}))

    with pytest.raises(ConfigError, match="mqtt_broker must be a string"):
        Setting(config_path=str(config_path))


def test_setting_parses_comma_separated_topics(tmp_path):
    config_path = tmp_path / "device_config.json"
    config_path.write_text(json.dumps({"mqtt_topic_sub": "topic/a, topic/b ,topic/c"}))

    setting = Setting(config_path=str(config_path))

    assert setting.MQTT_TOPIC_SUB == ["topic/a", "topic/b", "topic/c"]


def test_setting_parses_json_array_topics(tmp_path):
    config_path = tmp_path / "device_config.json"
    config_path.write_text(json.dumps({"mqtt_topic_sub": ["topic/a", "topic/b"]}))

    setting = Setting(config_path=str(config_path))

    assert setting.MQTT_TOPIC_SUB == ["topic/a", "topic/b"]


def test_setting_raises_on_empty_topics_list(tmp_path):
    config_path = tmp_path / "device_config.json"
    config_path.write_text(json.dumps({"mqtt_topic_sub": []}))

    with pytest.raises(ConfigError, match="mqtt_topic_sub"):
        Setting(config_path=str(config_path))


def test_setting_raises_on_non_string_topics_list_entry(tmp_path):
    config_path = tmp_path / "device_config.json"
    config_path.write_text(json.dumps({"mqtt_topic_sub": ["topic/a", 5]}))

    with pytest.raises(ConfigError, match="mqtt_topic_sub"):
        Setting(config_path=str(config_path))


def test_setting_raises_on_non_string_non_list_topics(tmp_path):
    config_path = tmp_path / "device_config.json"
    config_path.write_text(json.dumps({"mqtt_topic_sub": 5}))

    with pytest.raises(
        ConfigError, match="mqtt_topic_sub must be a string or list of strings"
    ):
        Setting(config_path=str(config_path))


def test_setting_collects_multiple_validation_errors(tmp_path):
    config_path = tmp_path / "device_config.json"
    config_path.write_text(json.dumps({"mqtt_port": "bad", "watchdog_enabled": "bad"}))

    with pytest.raises(ConfigError) as exc_info:
        Setting(config_path=str(config_path))

    message = str(exc_info.value)
    assert "mqtt_port" in message
    assert "watchdog_enabled" in message


def test_save_merges_new_values_without_clobbering_existing(tmp_path):
    config_path = tmp_path / "device_config.json"
    config_path.write_text(json.dumps({"mqtt_broker": "existing_broker"}))
    setting = Setting(config_path=str(config_path))

    setting.save(wifi_ssid="new_ssid", wifi_password="new_password")

    assert setting.WIFI_SSID == "new_ssid"
    assert setting.WIFI_PASSWORD == "new_password"
    assert setting.MQTT_BROKER == "existing_broker"

    on_disk = json.loads(config_path.read_text())
    assert on_disk["mqtt_broker"] == "existing_broker"
    assert on_disk["wifi_ssid"] == "new_ssid"
    assert on_disk["wifi_password"] == "new_password"


def test_save_creates_config_file_when_missing(tmp_path):
    config_path = tmp_path / "device_config.json"
    setting = Setting(config_path=str(config_path))

    setting.save(wifi_ssid="fresh_ssid")

    assert config_path.exists()
    on_disk = json.loads(config_path.read_text())
    assert on_disk["wifi_ssid"] == "fresh_ssid"


def test_save_skips_none_values(tmp_path):
    config_path = tmp_path / "device_config.json"
    config_path.write_text(json.dumps({"wifi_ssid": "existing_ssid"}))
    setting = Setting(config_path=str(config_path))

    saved = setting.save(wifi_ssid=None, wifi_password="new_password")

    assert saved == {"wifi_password": "new_password"}
    assert setting.WIFI_SSID == "existing_ssid"
    assert setting.WIFI_PASSWORD == "new_password"


def test_save_with_no_updates_is_a_noop(tmp_path):
    config_path = tmp_path / "device_config.json"
    setting = Setting(config_path=str(config_path))

    saved = setting.save()

    assert saved == {}
    assert not config_path.exists()


def test_save_raises_and_does_not_write_on_invalid_value(tmp_path):
    config_path = tmp_path / "device_config.json"
    config_path.write_text(json.dumps({"mqtt_broker": "existing_broker"}))
    setting = Setting(config_path=str(config_path))

    with pytest.raises(ConfigError, match="mqtt_port must be an integer"):
        setting.save(mqtt_port="not_a_number")

    assert setting.MQTT_PORT == 1883
    on_disk = json.loads(config_path.read_text())
    assert on_disk == {"mqtt_broker": "existing_broker"}


def test_save_returns_only_the_updated_keys(tmp_path):
    config_path = tmp_path / "device_config.json"
    setting = Setting(config_path=str(config_path))

    saved = setting.save(wifi_ssid="ssid_a", wifi_password="password_a")

    assert saved == {"wifi_ssid": "ssid_a", "wifi_password": "password_a"}
