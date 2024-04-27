import time
from umqtt.simple import MQTTClient
from environment import WIFI_SSID, WIFI_PASSWORD, MQTT_BROKER, MQTT_PORT, MQTT_CLIENT_ID, MQTT_TOPIC_PUB as MQTT_TOPIC
from app.services.wifi import WiFiService  # Assuming the WiFi service class is saved as wifi_service.py

class MosquittoService:
    def __init__(self):
        self.client_id = MQTT_CLIENT_ID
        self.mqtt_broker = MQTT_BROKER
        self.mqtt_port = MQTT_PORT
        self.topic = MQTT_TOPIC
        self.client = None
        self.wifi_service = WiFiService(WIFI_SSID, WIFI_PASSWORD)

    def connect_to_mqtt(self):
        self.client = MQTTClient(self.client_id, self.mqtt_broker, self.mqtt_port)
        try:
            print("Connecting to MQTT broker...")
            self.client.connect()  # Connect to the MQTT broker
            print("Connected to MQTT Broker at", self.mqtt_broker)
        except Exception as e:
            print("Failed to connect to MQTT broker:", e)
            self.client = None

    def publish_message(self, message):
        if self.client:
            try:
                print("Publishing message to topic:", self.topic)
                self.client.publish(self.topic, message.encode())  # Publish message
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

    def run(self):
        if not self.wifi_service.is_connected():
            self.wifi_service.connect()

        self.connect_to_mqtt()

        try:
            while True:
                self.publish_message("Hello from Agnes agent")
                time.sleep(1)
        finally:
            self.disconnect()


