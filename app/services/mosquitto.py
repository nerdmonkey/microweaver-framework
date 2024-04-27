import network
import time
from umqtt.simple import MQTTClient
from environment import WIFI_SSID, WIFI_PASSWORD, MQTT_BROKER, MQTT_PORT, MQTT_CLIENT_ID, MQTT_TOPIC_PUB as MQTT_TOPIC

class MosquittoService:
    def __init__(self):
        self.client_id = MQTT_CLIENT_ID
        self.mqtt_broker = MQTT_BROKER
        self.mqtt_port = MQTT_PORT
        self.topic = MQTT_TOPIC
        self.client = None
        self.wlan = network.WLAN(network.STA_IF)

    def connect_to_wifi(self):
        self.wlan.active(True)
        if not self.wlan.isconnected():
            print('Connecting to network...')
            self.wlan.connect(WIFI_SSID, WIFI_PASSWORD)
            while not self.wlan.isconnected():
                pass
        print('Network connected!')
        print('IP Address:', self.wlan.ifconfig()[0])

    def connect_to_mqtt(self):
        self.client = MQTTClient(self.client_id, self.mqtt_broker, self.mqtt_port)
        try:
            print("Connecting to MQTT broker...")
            self.client.connect()  # Connect to the MQTT broker
            print("Connected to MQTT Broker at", self.mqtt_broker)
        except Exception as e:
            print("Failed to connect to MQTT broker:", e)

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
        self.connect_to_wifi()
        if not self.wlan.isconnected():
            print("WiFi connection failed. Please check your settings.")
            return

        self.connect_to_mqtt()
        if self.client is None:
            print("MQTT connection failed. Please check your settings.")
            return

        try:
            while True:
                self.publish_message("Hello from Agnes agent")
                time.sleep(1)
        finally:
            self.disconnect()
