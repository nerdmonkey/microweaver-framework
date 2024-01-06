from environment import APP_ENVIRONMENT


class Mosquitto:
    def __init__(self, client_id, host, port, sub_topic, pub_topic):
        self.client_id = client_id
        self.host = host
        self.port = port
        self.sub_topic = sub_topic
        self.pub_topic = pub_topic

        # Conditional client setup based on environment
        if APP_ENVIRONMENT == "device":
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
