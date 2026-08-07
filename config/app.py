try:
    import ujson as json
except ImportError:
    import json

DEVICE_CONFIG_PATH = "device_config.json"

_SCHEMA = {
    "app_environment": {"type": str},
    "mqtt_enabled": {"type": bool},
    "mqtt_broker": {"type": str},
    "mqtt_client_id": {"type": str},
    "mqtt_port": {"type": "int", "min": 1, "max": 65535},
    "mqtt_topic_pub": {"type": str},
    "mqtt_topic_sub": {"type": "topics"},
    "mqtt_username": {"type": str},
    "mqtt_password": {"type": str},
    "wifi_ssid": {"type": str},
    "wifi_password": {"type": str},
    "wifi_ip": {"type": str},
    "wifi_subnet": {"type": str},
    "wifi_gateway": {"type": str},
    "wifi_dns": {"type": str},
    "wifi_disable_power_save": {"type": bool},
    "wifi_connect_timeout_seconds": {"type": "int", "min": 0},
    "wifi_reconnect_delay_seconds": {"type": "int", "min": 0},
    "wifi_max_reconnect_delay_seconds": {"type": "int", "min": 0},
    "mqtt_reconnect_delay_seconds": {"type": "int", "min": 0},
    "mqtt_max_reconnect_delay_seconds": {"type": "int", "min": 0},
    "mqtt_keepalive_seconds": {"type": "int", "min": 0},
    "mqtt_ssl": {"type": bool},
    "mqtt_ssl_cert_path": {"type": str},
    "mqtt_ssl_key_path": {"type": str},
    "mqtt_lwt_topic": {"type": str},
    "mqtt_lwt_message": {"type": str},
    "mqtt_lwt_retain": {"type": bool},
    "mqtt_lwt_qos": {"type": "int", "min": 0, "max": 1},
    "mqtt_publish_retain": {"type": bool},
    "mqtt_publish_qos": {"type": "int", "min": 0, "max": 1},
    "watchdog_enabled": {"type": bool},
    "watchdog_timeout_ms": {"type": "int", "min": 0},
    "boot_loop_protection_enabled": {"type": bool},
    "boot_loop_max_attempts": {"type": "int", "min": 0},
    "boot_loop_state_path": {"type": str},
    "boot_interrupt_window_seconds": {"type": "int", "min": 0},
    "autostart_enabled": {"type": bool},
    "safe_mode_sleep_seconds": {"type": "int", "min": 0},
    "memory_monitor_enabled": {"type": bool},
    "memory_monitor_threshold_bytes": {"type": "int", "min": 0},
    "memory_monitor_action": {"type": str, "choices": ("log", "warn", "restart")},
    "health_check_enabled": {"type": bool},
    "health_check_interval_seconds": {"type": "int", "min": 0},
    "service_restart_enabled": {"type": bool},
    "service_restart_max_attempts": {"type": "int", "min": 0},
    "log_format": {"type": str, "choices": ("json", "kv")},
    "dht22_pin": {"type": "int", "min": 0, "max": 39},
    "relay_pin": {"type": "int", "min": 0, "max": 39},
    "provisioning_ap_ssid": {"type": str},
    "provisioning_ap_password": {"type": str},
    "provisioning_ap_ip": {"type": str},
    "provisioning_port": {"type": "int", "min": 1, "max": 65535},
    "provisioning_led_enabled": {"type": bool},
    "provisioning_led_pin": {"type": "int", "min": 0, "max": 39},
    "factory_reset_enabled": {"type": bool},
    "factory_reset_pin": {"type": "int", "min": -1, "max": 39},
    "factory_reset_hold_seconds": {"type": "int", "min": 0},
    "factory_reset_sentinel_path": {"type": str},
    "claim_enabled": {"type": bool},
    "claim_url": {"type": str},
    "claim_code": {"type": str},
    "device_id": {"type": str},
    "device_cert": {"type": str},
    "device_key": {"type": str},
}


class ConfigError(Exception):
    """Raised when device_config.json fails schema validation."""


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


class Setting:
    def __init__(self, config_path=DEVICE_CONFIG_PATH):
        self._config_path = config_path
        self._config = self._load(config_path)
        self._apply_config()

    def _apply_config(self):
        self.APP_ENVIRONMENT = self._value("app_environment", "local")
        self.MQTT_ENABLED = self._bool("mqtt_enabled", True)
        self.MQTT_BROKER = self._value("mqtt_broker", "localhost")
        self.MQTT_CLIENT_ID = self._value("mqtt_client_id", "microweaver")
        self.MQTT_PORT = self._int("mqtt_port", 1883)
        self.MQTT_TOPIC_PUB = self._value(
            "mqtt_topic_pub", "command/control/room/light"
        )
        self.MQTT_TOPIC_SUB = self._topics(
            "mqtt_topic_sub", "data/sensor/room/temperature"
        )
        self.MQTT_USERNAME = self._value("mqtt_username", "")
        self.MQTT_PASSWORD = self._value("mqtt_password", "")
        self.WIFI_SSID = self._value("wifi_ssid", "")
        self.WIFI_PASSWORD = self._value("wifi_password", "")
        self.WIFI_IP = self._value("wifi_ip", "")
        self.WIFI_SUBNET = self._value("wifi_subnet", "")
        self.WIFI_GATEWAY = self._value("wifi_gateway", "")
        self.WIFI_DNS = self._value("wifi_dns", "")
        self.WIFI_DISABLE_POWER_SAVE = self._bool("wifi_disable_power_save", False)

        self.WIFI_CONNECT_TIMEOUT_SECONDS = self._int(
            "wifi_connect_timeout_seconds", 20
        )
        self.WIFI_RECONNECT_DELAY_SECONDS = self._int("wifi_reconnect_delay_seconds", 2)
        self.WIFI_MAX_RECONNECT_DELAY_SECONDS = self._int(
            "wifi_max_reconnect_delay_seconds", 30
        )
        self.MQTT_RECONNECT_DELAY_SECONDS = self._int("mqtt_reconnect_delay_seconds", 2)
        self.MQTT_MAX_RECONNECT_DELAY_SECONDS = self._int(
            "mqtt_max_reconnect_delay_seconds", 30
        )
        self.MQTT_KEEPALIVE_SECONDS = self._int("mqtt_keepalive_seconds", 300)
        self.MQTT_SSL = self._bool("mqtt_ssl", False)
        self.MQTT_SSL_CERT_PATH = self._value("mqtt_ssl_cert_path", "")
        self.MQTT_SSL_KEY_PATH = self._value("mqtt_ssl_key_path", "")
        self.MQTT_LWT_TOPIC = self._value("mqtt_lwt_topic", "")
        self.MQTT_LWT_MESSAGE = self._value("mqtt_lwt_message", "")
        self.MQTT_LWT_RETAIN = self._bool("mqtt_lwt_retain", False)
        self.MQTT_LWT_QOS = self._int("mqtt_lwt_qos", 0)
        self.MQTT_PUBLISH_RETAIN = self._bool("mqtt_publish_retain", False)
        self.MQTT_PUBLISH_QOS = self._int("mqtt_publish_qos", 0)

        self.WATCHDOG_ENABLED = self._bool("watchdog_enabled", False)
        self.WATCHDOG_TIMEOUT_MS = self._int("watchdog_timeout_ms", 8000)

        self.BOOT_LOOP_PROTECTION_ENABLED = self._bool(
            "boot_loop_protection_enabled", False
        )
        self.BOOT_LOOP_MAX_ATTEMPTS = self._int("boot_loop_max_attempts", 5)
        self.BOOT_LOOP_STATE_PATH = self._value(
            "boot_loop_state_path", "boot_state.json"
        )
        self.BOOT_INTERRUPT_WINDOW_SECONDS = self._int(
            "boot_interrupt_window_seconds", 2
        )
        self.AUTOSTART_ENABLED = self._bool("autostart_enabled", True)

        self.SAFE_MODE_SLEEP_SECONDS = self._int("safe_mode_sleep_seconds", 5)

        self.MEMORY_MONITOR_ENABLED = self._bool("memory_monitor_enabled", False)
        self.MEMORY_MONITOR_THRESHOLD_BYTES = self._int(
            "memory_monitor_threshold_bytes", 10000
        )
        self.MEMORY_MONITOR_ACTION = self._value("memory_monitor_action", "log")

        self.HEALTH_CHECK_ENABLED = self._bool("health_check_enabled", False)
        self.HEALTH_CHECK_INTERVAL_SECONDS = self._int(
            "health_check_interval_seconds", 30
        )

        self.SERVICE_RESTART_ENABLED = self._bool("service_restart_enabled", False)
        self.SERVICE_RESTART_MAX_ATTEMPTS = self._int("service_restart_max_attempts", 3)

        self.LOG_FORMAT = self._value("log_format", "json")

        self.DHT22_PIN = self._int("dht22_pin", 4)
        self.RELAY_PIN = self._int("relay_pin", 5)

        self.PROVISIONING_AP_SSID = self._value(
            "provisioning_ap_ssid", "Microweaver-Setup"
        )
        self.PROVISIONING_AP_PASSWORD = self._value("provisioning_ap_password", "")
        self.PROVISIONING_AP_IP = self._value("provisioning_ap_ip", "192.168.4.1")
        self.PROVISIONING_PORT = self._int("provisioning_port", 80)
        self.PROVISIONING_LED_ENABLED = self._bool("provisioning_led_enabled", False)
        self.PROVISIONING_LED_PIN = self._int("provisioning_led_pin", 2)

        self.FACTORY_RESET_ENABLED = self._bool("factory_reset_enabled", False)
        self.FACTORY_RESET_PIN = self._int("factory_reset_pin", -1)
        self.FACTORY_RESET_HOLD_SECONDS = self._int("factory_reset_hold_seconds", 3)
        self.FACTORY_RESET_SENTINEL_PATH = self._value(
            "factory_reset_sentinel_path", "reprovision.flag"
        )

        self.CLAIM_ENABLED = self._bool("claim_enabled", False)
        self.CLAIM_URL = self._value("claim_url", "")
        self.CLAIM_CODE = self._value("claim_code", "")
        self.DEVICE_ID = self._value("device_id", "")
        self.DEVICE_CERT = self._value("device_cert", "")
        self.DEVICE_KEY = self._value("device_key", "")

    def _load(self, path):
        try:
            with open(path, "r") as config_file:
                config = json.load(config_file)
        except Exception:
            return {}

        self._validate(config)
        return config

    def save(self, **values):
        updates = {key: value for key, value in values.items() if value is not None}
        if not updates:
            return {}

        merged = dict(self._config)
        merged.update(updates)
        self._validate(merged)

        with open(self._config_path, "w") as config_file:
            json.dump(merged, config_file)

        self._config = merged
        self._apply_config()
        return updates

    def _validate(self, config):
        errors = []
        for key, rules in _SCHEMA.items():
            if key not in config:
                continue
            errors.extend(self._validate_field(key, config[key], rules))

        if errors:
            raise ConfigError(
                "device_config.json failed validation: " + "; ".join(errors)
            )

    def _validate_field(self, key, value, rules):
        expected = rules["type"]

        if expected == "int":
            return self._validate_int(key, value, rules)
        if expected == "topics":
            return self._validate_topics(key, value)
        if expected is bool:
            if not isinstance(value, bool):
                return ["{} must be a boolean, got {}".format(key, value)]
            return []

        if not isinstance(value, str):
            return ["{} must be a string, got {}".format(key, value)]
        choices = rules.get("choices")
        if choices and value not in choices:
            return ["{} must be one of {}, got {}".format(key, choices, value)]
        return []

    def _validate_topics(self, key, value):
        if isinstance(value, str):
            return []
        if isinstance(value, list):
            if value and all(isinstance(item, str) for item in value):
                return []
            return ["{} list entries must be non-empty strings".format(key)]
        return ["{} must be a string or list of strings, got {}".format(key, value)]

    def _validate_int(self, key, value, rules):
        if not _is_int(value):
            return ["{} must be an integer, got {}".format(key, value)]

        errors = []
        min_value = rules.get("min")
        max_value = rules.get("max")
        if min_value is not None and value < min_value:
            errors.append("{} must be >= {}, got {}".format(key, min_value, value))
        if max_value is not None and value > max_value:
            errors.append("{} must be <= {}, got {}".format(key, max_value, value))
        return errors

    def _value(self, key, default):
        value = self._config.get(key)
        if value is None or value == "":
            return default
        return value

    def _int(self, key, default):
        return int(self._value(key, default))

    def _topics(self, key, default):
        value = self._value(key, default)
        if isinstance(value, list):
            return [str(item) for item in value]
        return [topic.strip() for topic in str(value).split(",") if topic.strip()]

    def _bool(self, key, default):
        value = self._config.get(key)
        if value is None:
            return default
        return bool(value)

    def get_settings(self):
        return self
