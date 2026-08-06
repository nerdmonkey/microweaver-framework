try:
    import ujson as json
except ImportError:
    import json

DEVICE_CONFIG_PATH = "device_config.json"

_SCHEMA = {
    "app_environment": {"type": str},
    "mqtt_broker": {"type": str},
    "mqtt_client_id": {"type": str},
    "mqtt_port": {"type": "int", "min": 1, "max": 65535},
    "mqtt_topic_pub": {"type": str},
    "mqtt_topic_sub": {"type": str},
    "mqtt_username": {"type": str},
    "mqtt_password": {"type": str},
    "wifi_ssid": {"type": str},
    "wifi_password": {"type": str},
    "wifi_connect_timeout_seconds": {"type": "int", "min": 0},
    "mqtt_reconnect_delay_seconds": {"type": "int", "min": 0},
    "mqtt_max_reconnect_delay_seconds": {"type": "int", "min": 0},
    "mqtt_keepalive_seconds": {"type": "int", "min": 0},
    "watchdog_enabled": {"type": bool},
    "watchdog_timeout_ms": {"type": "int", "min": 0},
    "boot_loop_protection_enabled": {"type": bool},
    "boot_loop_max_attempts": {"type": "int", "min": 0},
    "boot_loop_state_path": {"type": str},
    "safe_mode_sleep_seconds": {"type": "int", "min": 0},
    "memory_monitor_enabled": {"type": bool},
    "memory_monitor_threshold_bytes": {"type": "int", "min": 0},
    "memory_monitor_action": {"type": str, "choices": ("log", "warn", "restart")},
    "health_check_enabled": {"type": bool},
    "health_check_interval_seconds": {"type": "int", "min": 0},
    "service_restart_enabled": {"type": bool},
    "service_restart_max_attempts": {"type": "int", "min": 0},
    "log_format": {"type": str, "choices": ("json", "kv")},
}


class ConfigError(Exception):
    """Raised when device_config.json fails schema validation."""


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


class Setting:
    def __init__(self, config_path=DEVICE_CONFIG_PATH):
        self._config = self._load(config_path)

        self.APP_ENVIRONMENT = self._value("app_environment", "local")
        self.MQTT_BROKER = self._value("mqtt_broker", "localhost")
        self.MQTT_CLIENT_ID = self._value("mqtt_client_id", "microweaver")
        self.MQTT_PORT = self._int("mqtt_port", 1883)
        self.MQTT_TOPIC_PUB = self._value(
            "mqtt_topic_pub", "command/control/room/light"
        )
        self.MQTT_TOPIC_SUB = self._value(
            "mqtt_topic_sub", "data/sensor/room/temperature"
        )
        self.MQTT_USERNAME = self._value("mqtt_username", "")
        self.MQTT_PASSWORD = self._value("mqtt_password", "")
        self.WIFI_SSID = self._value("wifi_ssid", "")
        self.WIFI_PASSWORD = self._value("wifi_password", "")

        self.WIFI_CONNECT_TIMEOUT_SECONDS = self._int(
            "wifi_connect_timeout_seconds", 20
        )
        self.MQTT_RECONNECT_DELAY_SECONDS = self._int("mqtt_reconnect_delay_seconds", 2)
        self.MQTT_MAX_RECONNECT_DELAY_SECONDS = self._int(
            "mqtt_max_reconnect_delay_seconds", 30
        )
        self.MQTT_KEEPALIVE_SECONDS = self._int("mqtt_keepalive_seconds", 300)

        self.WATCHDOG_ENABLED = self._bool("watchdog_enabled", False)
        self.WATCHDOG_TIMEOUT_MS = self._int("watchdog_timeout_ms", 8000)

        self.BOOT_LOOP_PROTECTION_ENABLED = self._bool(
            "boot_loop_protection_enabled", False
        )
        self.BOOT_LOOP_MAX_ATTEMPTS = self._int("boot_loop_max_attempts", 5)
        self.BOOT_LOOP_STATE_PATH = self._value(
            "boot_loop_state_path", "boot_state.json"
        )

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

    def _load(self, path):
        try:
            with open(path, "r") as config_file:
                config = json.load(config_file)
        except Exception:
            return {}

        self._validate(config)
        return config

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

    def _bool(self, key, default):
        value = self._config.get(key)
        if value is None:
            return default
        return bool(value)

    def get_settings(self):
        return self
