import time

from umqtt.simple import MQTTClient


class MqttConnection:
    def __init__(
        self,
        client_id,
        broker,
        port,
        wifi_service,
        reconnect_delay_seconds=2,
        max_reconnect_delay_seconds=30,
        keepalive_seconds=300,
        watchdog_service=None,
        username=None,
        password=None,
    ):
        self.client_id = client_id
        self.broker = broker
        self.port = port
        self.wifi_service = wifi_service
        self.reconnect_delay_seconds = reconnect_delay_seconds
        self.max_reconnect_delay_seconds = max_reconnect_delay_seconds
        self.keepalive_seconds = keepalive_seconds
        self.watchdog_service = watchdog_service
        self.username = username
        self.password = password
        self.client = None

    def connect(self):
        if not self.wifi_service.is_connected():
            self.wifi_service.connect()

        delay = self.reconnect_delay_seconds
        while True:
            if self.watchdog_service:
                self.watchdog_service.feed()
            try:
                client_kwargs = {"keepalive": self.keepalive_seconds}
                if self.username:
                    client_kwargs["user"] = self.username
                    client_kwargs["password"] = self.password
                self.client = MQTTClient(
                    self.client_id,
                    self.broker,
                    self.port,
                    **client_kwargs,
                )
                self.client.connect()
                print("Connected to MQTT Broker at", self.broker)
                return self.client
            except Exception as e:
                print(
                    "Failed to connect to MQTT broker:", e, "- retrying in", delay, "s"
                )
                time.sleep(delay)
                delay = min(delay * 2, self.max_reconnect_delay_seconds)
                if not self.wifi_service.is_connected():
                    self.wifi_service.connect()

    def disconnect(self):
        if self.client:
            try:
                self.client.disconnect()
                print("Disconnected from MQTT Broker")
            except Exception as e:
                print("Failed to disconnect from MQTT broker:", e)
            finally:
                self.client = None
