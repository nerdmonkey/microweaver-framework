import json
from app.route import handle

from environment import (
    APP_ENVIRONMENT,
    MQTT_BROKER,
    MQTT_CLIENT_ID,
    MQTT_PORT,
    MQTT_TOPIC_PUB,
    MQTT_TOPIC_SUB,
)


class Mosquitto:
    def __init__(self):
        self.client_id = MQTT_CLIENT_ID
        self.host = MQTT_BROKER
        self.port = MQTT_PORT
        self.sub_topic = MQTT_TOPIC_SUB
        self.pub_topic = MQTT_TOPIC_PUB

        if APP_ENVIRONMENT == "device":
            print("Using umqtt client")
            from umqtt.simple import MQTTClient as MQTTClient

            self.client = MQTTClient(self.client_id, self.host, self.port)
        else:
            import paho.mqtt.client as mqtt

            self.client = mqtt.Client(self.client_id)
            self.client.on_connect = self.on_connect
            self.client.on_message = self.on_message
            self.client.on_publish = self.on_publish

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            print("Connected to MQTT Broker!")
            client.subscribe(self.sub_topic)
        else:
            print(f"Failed to connect, return code {rc}")

    def on_message(self, client, userdata, msg):
        try:
            payload = msg.payload.decode()
            if payload.startswith("{") and payload.endswith("}"):
                payload = json.loads(payload)
            else:
                raise ValueError("Payload is not a json")

            handle(msg)

        except Exception as e:
            print(f"An error occurred: {e}")

        print(f"Received `{msg.payload.decode()}` from `{msg.topic}` topic")

    def on_publish(self, client, userdata, mid):
        print(f"Message {mid} published to {self.pub_topic}")

    def publish(self, topic, message):
        self.client.publish(topic, message)

    def start(self):
        self.client.connect(self.host, self.port)
        self.client.loop_start()

    def stop(self):
        self.client.loop_stop()
        self.client.disconnect()

    def subscribe(self):
        self.client.connect(self.host, self.port)
        self.client.loop_forever()
