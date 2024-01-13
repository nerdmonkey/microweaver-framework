import json

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
        payload = json.loads(msg.payload.decode())
        print(payload)

        if msg.topic == "command/control/motor":
            print("Received message from motor")
            self.publish("Received message from motor")
        elif msg.topic == "data/sensor/temperature":
            print("Received message from temperature")
            self.publish("Received message from temperature")
        else:
            pass

        print(f"Received `{msg.payload.decode()}` from `{msg.topic}` topic")

    def on_publish(self, client, userdata, mid):
        print(f"Message {mid} published to {self.pub_topic}")

    def publish(self, message):
        self.client.publish(self.pub_topic, message)

    def start(self):
        self.client.connect(self.host, self.port)
        self.client.loop_start()

    def stop(self):
        self.client.loop_stop()
        self.client.disconnect()

    def subscribe(self):
        self.client.connect(self.host, self.port)
        self.client.loop_forever()
