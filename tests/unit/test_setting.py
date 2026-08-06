import json

import pytest

from config.app import ConfigError, Setting


def test_setting_reads_values_from_device_config(tmp_path):
    config_path = tmp_path / "device_config.json"
    config_path.write_text(
        json.dumps(
            {
                "app_environment": "test",
                "mqtt_broker": "test_broker",
                "mqtt_client_id": "test_id",
                "mqtt_port": 1884,
                "mqtt_topic_pub": "test/pub",
                "mqtt_topic_sub": "test/sub",
                "mqtt_username": "test_user",
                "mqtt_password": "test_pass",
                "wifi_ssid": "test_ssid",
                "wifi_password": "test_password",
                "wifi_connect_timeout_seconds": 5,
                "wifi_reconnect_delay_seconds": 3,
                "wifi_max_reconnect_delay_seconds": 20,
                "mqtt_reconnect_delay_seconds": 1,
                "mqtt_max_reconnect_delay_seconds": 10,
                "mqtt_keepalive_seconds": 60,
                "watchdog_enabled": True,
                "watchdog_timeout_ms": 5000,
                "boot_loop_protection_enabled": True,
                "boot_loop_max_attempts": 3,
                "boot_loop_state_path": "test_boot_state.json",
                "safe_mode_sleep_seconds": 2,
                "memory_monitor_enabled": True,
                "memory_monitor_threshold_bytes": 20000,
                "memory_monitor_action": "warn",
                "health_check_enabled": True,
                "health_check_interval_seconds": 15,
                "service_restart_enabled": True,
                "service_restart_max_attempts": 7,
                "log_format": "kv",
            }
        )
    )

    setting = Setting(config_path=str(config_path))

    assert setting.APP_ENVIRONMENT == "test"
    assert setting.MQTT_BROKER == "test_broker"
    assert setting.MQTT_CLIENT_ID == "test_id"
    assert setting.MQTT_PORT == 1884
    assert setting.MQTT_TOPIC_PUB == "test/pub"
    assert setting.MQTT_TOPIC_SUB == "test/sub"
    assert setting.MQTT_USERNAME == "test_user"
    assert setting.MQTT_PASSWORD == "test_pass"
    assert setting.WIFI_SSID == "test_ssid"
    assert setting.WIFI_PASSWORD == "test_password"
    assert setting.WIFI_CONNECT_TIMEOUT_SECONDS == 5
    assert setting.WIFI_RECONNECT_DELAY_SECONDS == 3
    assert setting.WIFI_MAX_RECONNECT_DELAY_SECONDS == 20
    assert setting.MQTT_RECONNECT_DELAY_SECONDS == 1
    assert setting.MQTT_MAX_RECONNECT_DELAY_SECONDS == 10
    assert setting.MQTT_KEEPALIVE_SECONDS == 60
    assert setting.WATCHDOG_ENABLED is True
    assert setting.WATCHDOG_TIMEOUT_MS == 5000
    assert setting.BOOT_LOOP_PROTECTION_ENABLED is True
    assert setting.BOOT_LOOP_MAX_ATTEMPTS == 3
    assert setting.BOOT_LOOP_STATE_PATH == "test_boot_state.json"
    assert setting.SAFE_MODE_SLEEP_SECONDS == 2
    assert setting.MEMORY_MONITOR_ENABLED is True
    assert setting.MEMORY_MONITOR_THRESHOLD_BYTES == 20000
    assert setting.MEMORY_MONITOR_ACTION == "warn"
    assert setting.HEALTH_CHECK_ENABLED is True
    assert setting.HEALTH_CHECK_INTERVAL_SECONDS == 15
    assert setting.SERVICE_RESTART_ENABLED is True
    assert setting.SERVICE_RESTART_MAX_ATTEMPTS == 7
    assert setting.LOG_FORMAT == "kv"


def test_setting_falls_back_to_defaults_when_file_missing(tmp_path):
    missing_path = tmp_path / "does_not_exist.json"

    setting = Setting(config_path=str(missing_path))

    assert setting.APP_ENVIRONMENT == "local"
    assert setting.MQTT_BROKER == "localhost"
    assert setting.MQTT_CLIENT_ID == "microweaver"
    assert setting.MQTT_PORT == 1883
    assert setting.WIFI_SSID == ""
    assert setting.WIFI_PASSWORD == ""
    assert setting.WIFI_CONNECT_TIMEOUT_SECONDS == 20
    assert setting.WIFI_RECONNECT_DELAY_SECONDS == 2
    assert setting.WIFI_MAX_RECONNECT_DELAY_SECONDS == 30
    assert setting.MQTT_RECONNECT_DELAY_SECONDS == 2
    assert setting.MQTT_MAX_RECONNECT_DELAY_SECONDS == 30
    assert setting.MQTT_KEEPALIVE_SECONDS == 300
    assert setting.WATCHDOG_ENABLED is False
    assert setting.WATCHDOG_TIMEOUT_MS == 8000
    assert setting.BOOT_LOOP_PROTECTION_ENABLED is False
    assert setting.BOOT_LOOP_MAX_ATTEMPTS == 5
    assert setting.BOOT_LOOP_STATE_PATH == "boot_state.json"
    assert setting.SAFE_MODE_SLEEP_SECONDS == 5
    assert setting.MEMORY_MONITOR_ENABLED is False
    assert setting.MEMORY_MONITOR_THRESHOLD_BYTES == 10000
    assert setting.MEMORY_MONITOR_ACTION == "log"
    assert setting.HEALTH_CHECK_ENABLED is False
    assert setting.HEALTH_CHECK_INTERVAL_SECONDS == 30
    assert setting.SERVICE_RESTART_ENABLED is False
    assert setting.SERVICE_RESTART_MAX_ATTEMPTS == 3
    assert setting.LOG_FORMAT == "json"


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


def test_setting_raises_on_non_string_field(tmp_path):
    config_path = tmp_path / "device_config.json"
    config_path.write_text(json.dumps({"mqtt_broker": 12345}))

    with pytest.raises(ConfigError, match="mqtt_broker must be a string"):
        Setting(config_path=str(config_path))


def test_setting_collects_multiple_validation_errors(tmp_path):
    config_path = tmp_path / "device_config.json"
    config_path.write_text(json.dumps({"mqtt_port": "bad", "watchdog_enabled": "bad"}))

    with pytest.raises(ConfigError) as exc_info:
        Setting(config_path=str(config_path))

    message = str(exc_info.value)
    assert "mqtt_port" in message
    assert "watchdog_enabled" in message
