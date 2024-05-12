import environment


class Setting:
    def __init__(self):
        self.APP_ENVIRONMENT = environment.APP_ENVIRONMENT
        self.MQTT_BROKER = environment.MQTT_BROKER
        self.MQTT_CLIENT_ID = environment.MQTT_CLIENT_ID
        self.MQTT_PORT = environment.MQTT_PORT
        self.MQTT_TOPIC_PUB = environment.MQTT_TOPIC_PUB
        self.MQTT_TOPIC_SUB = environment.MQTT_TOPIC_SUB
        self.MQTT_USERNAME = environment.MQTT_USERNAME
        self.MQTT_PASSWORD = environment.MQTT_PASSWORD
        self.WIFI_SSID = environment.WIFI_SSID
        self.WIFI_PASSWORD = environment.WIFI_PASSWORD


    def get_settings(self):
        return self
