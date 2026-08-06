import time

from app.services.bootloop import BootLoopGuard
from app.services.memory_monitor import MemoryMonitorService
from app.services.mqtt import MqttConnection
from app.services.watchdog import WatchdogService
from app.services.wifi import WiFiService
from config.app import Setting

setting = (Setting()).get_settings()


class PublishService:
    def __init__(self):
        self.topic = setting.MQTT_TOPIC_PUB
        self.wifi_service = WiFiService(
            setting.WIFI_SSID,
            setting.WIFI_PASSWORD,
            setting.WIFI_CONNECT_TIMEOUT_SECONDS,
        )
        self.watchdog_service = None
        if setting.WATCHDOG_ENABLED:
            self.watchdog_service = WatchdogService(setting.WATCHDOG_TIMEOUT_MS)
            self.watchdog_service.start()
        self.bootloop_guard = None
        if setting.BOOT_LOOP_PROTECTION_ENABLED:
            self.bootloop_guard = BootLoopGuard(
                setting.BOOT_LOOP_STATE_PATH, setting.BOOT_LOOP_MAX_ATTEMPTS
            )
        self.memory_monitor_service = None
        if setting.MEMORY_MONITOR_ENABLED:
            self.memory_monitor_service = MemoryMonitorService(
                setting.MEMORY_MONITOR_THRESHOLD_BYTES, setting.MEMORY_MONITOR_ACTION
            )
        self.connection = MqttConnection(
            setting.MQTT_CLIENT_ID,
            setting.MQTT_BROKER,
            setting.MQTT_PORT,
            self.wifi_service,
            setting.MQTT_RECONNECT_DELAY_SECONDS,
            setting.MQTT_MAX_RECONNECT_DELAY_SECONDS,
            setting.MQTT_KEEPALIVE_SECONDS,
            self.watchdog_service,
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
            if self.bootloop_guard:
                self.bootloop_guard.confirm()
            try:
                while True:
                    if self.watchdog_service:
                        self.watchdog_service.feed()
                    if self.memory_monitor_service:
                        self.memory_monitor_service.check()
                    self.publish_message(message)
                    time.sleep(1)
            except Exception as e:
                print("Connection lost:", e)
            finally:
                self.disconnect()
