class PubSubService:
    def __init__(self, connection):
        self.connection = connection
        self.client = None

    def connect(self):
        self.client = self.connection.connect()
        return self.client

    def disconnect(self):
        self.connection.disconnect()
        self.client = None

    def publish(self, topic, message):
        if not self.client:
            print("Not connected to MQTT.")
            return
        try:
            self.client.publish(topic, message.encode())
            print("Published message to topic:", topic)
        except Exception as e:
            print("Failed to publish message to", topic, ":", e)

    def subscribe(self, topic, callback):
        if not self.client:
            print("Not connected to MQTT.")
            return
        self.client.set_callback(callback)
        self.client.subscribe(topic)
        print("Subscribed to topic:", topic)

    def check_messages(self):
        if not self.client:
            return
        self.client.check_msg()
