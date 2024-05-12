import time
from umqtt.simple import MQTTClient
from config.app import Setting
from app.services.wifi import WiFiService


setting = (Setting()).get_settings()


class PublishService:
    def __init__(self):
        self.client_id = setting.MQTT_CLIENT_ID
        self.mqtt_broker = setting.MQTT_BROKER
        self.mqtt_port = setting.MQTT_PORT
        self.topic = setting.MQTT_TOPIC_PUB
        self.client = None
        self.wifi_service = WiFiService(setting.WIFI_SSID, setting.WIFI_PASSWORD)

    def connect_to_mqtt(self):
        self.client = MQTTClient(self.client_id, self.mqtt_broker, self.mqtt_port)
        try:
            print("Connecting to MQTT broker...")
            self.client.connect()
            print("Connected to MQTT Broker at", self.mqtt_broker)
        except Exception as e:
            print("Failed to connect to MQTT broker:", e)
            self.client = None

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
        if self.client:
            try:
                self.client.disconnect()
                print("Disconnected from MQTT Broker")
            except Exception as e:
                print("Failed to disconnect from MQTT broker:", e)

    def run(self, message="Hello from Agnes agent"):
        if not self.wifi_service.is_connected():
            self.wifi_service.connect()

        self.connect_to_mqtt()

        try:
            while True:
                self.publish_message(message)
                time.sleep(1)
        finally:
            self.disconnect()
