import time
from config.app import Setting
from app.services.wifi import WiFiService
from app.services.mqtt import MqttConnection


setting = (Setting()).get_settings()


class PublishService:
    def __init__(self):
        self.topic = setting.MQTT_TOPIC_PUB
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

    def connect_to_mqtt(self):
        self.client = self.connection.connect()

    def publish_message(self, message):
        if self.client:
            try:
                print("Publishing message to topic:", self.topic)
                self.client.publish(self.topic, message.encode())
                print("Message published")
            except Exception as e:
                print("Failed to publish message:", e)
        else:
            print("Not connected to MQTT.")

    def disconnect(self):
        self.connection.disconnect()
        self.client = None

    def run(self, message="Hello from Agnes agent"):
        while True:
            self.connect_to_mqtt()
            try:
                while True:
                    self.publish_message(message)
                    time.sleep(1)
            except Exception as e:
                print("Connection lost:", e)
            finally:
                self.disconnect()
