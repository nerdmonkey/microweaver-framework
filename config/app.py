try:
    import ujson as json
except ImportError:
    import json

DEVICE_CONFIG_PATH = "device_config.json"


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

    def _load(self, path):
        try:
            with open(path, "r") as config_file:
                return json.load(config_file)
        except Exception:
            return {}

    def _value(self, key, default):
        value = self._config.get(key)
        if value is None or value == "":
            return default
        return value

    def _int(self, key, default):
        try:
            return int(self._value(key, default))
        except Exception:
            return default

    def get_settings(self):
        return self
