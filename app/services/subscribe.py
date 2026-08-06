import time

from app.services.bootloop import BootLoopGuard
from app.services.health import HealthCheckService
from app.services.memory_monitor import MemoryMonitorService
from app.services.mqtt import MqttConnection
from app.services.watchdog import WatchdogService
from app.services.wifi import WiFiService
from config.app import Setting

setting = (Setting()).get_settings()


class SubscribeService:
    def __init__(self):
        self.topic = setting.MQTT_TOPIC_SUB
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
        self.health_check_service = None
        if setting.HEALTH_CHECK_ENABLED:
            self.health_check_service = HealthCheckService(
                interval_seconds=setting.HEALTH_CHECK_INTERVAL_SECONDS
            )
            self.health_check_service.register("wifi", self.wifi_service.is_connected)
            self.health_check_service.register("mqtt", lambda: self.client is not None)
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

    def on_message(self, topic, message):
        print("Received message on topic:", topic.decode(), "-", message.decode())

    def connect_to_mqtt(self):
        self.client = self.connection.connect()
        self.client.set_callback(self.on_message)
        self.client.subscribe(self.topic)
        print("Subscribed to topic:", self.topic)

    def disconnect(self):
        self.connection.disconnect()
        self.client = None

    def run(self):
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
                    if self.health_check_service:
                        self.health_check_service.poll()
                    self.client.check_msg()
                    time.sleep(1)
            except Exception as e:
                print("Connection lost:", e)
            finally:
                self.disconnect()
