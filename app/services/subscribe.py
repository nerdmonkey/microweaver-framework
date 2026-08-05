from app.services.mqtt import MqttConnection
from app.services.wifi import WiFiService
from config.app import Setting

setting = (Setting()).get_settings()


class SubscribeService:
    def __init__(self):
        self.topic = setting.MQTT_TOPIC_SUB
        self.wifi_service = WiFiService(
            setting.WIFI_SSID,
            setting.WIFI_PASSWORD,
            setting.WIFI_CONNECT_TIMEOUT_SECONDS,
        )
        self.connection = MqttConnection(
            setting.MQTT_CLIENT_ID,
            setting.MQTT_BROKER,
            setting.MQTT_PORT,
            self.wifi_service,
            setting.MQTT_RECONNECT_DELAY_SECONDS,
            setting.MQTT_MAX_RECONNECT_DELAY_SECONDS,
            setting.MQTT_KEEPALIVE_SECONDS,
        )
        self.client = None

    def on_message(self, topic, message):
        print("Received message on topic:", topic.decode(), "-", message.decode())

    def connect_to_mqtt(self):
        self.client = self.connection.connect()
        self.client.set_callback(self.on_message)
        self.client.subscribe(self.topic)
        print("Subscribed to topic:", self.topic)

    def disconnect(self):
        self.connection.disconnect()
        self.client = None

    def run(self):
        while True:
            self.connect_to_mqtt()
            try:
                while True:
                    self.client.wait_msg()
            except Exception as e:
                print("Connection lost:", e)
            finally:
                self.disconnect()
