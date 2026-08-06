import time

from app.services.bootloop import BootLoopGuard
from app.services.health import HealthCheckService
from app.services.logger import LogService
from app.services.memory_monitor import MemoryMonitorService
from app.services.mqtt import MqttConnection
from app.services.registry import ServiceRegistry
from app.services.service_restart import ServiceRestartService
from app.services.watchdog import WatchdogService
from app.services.wifi import WiFiService
from config.app import Setting

setting = (Setting()).get_settings()


class SubscribeService:
    def __init__(self):
        self.topic = setting.MQTT_TOPIC_SUB
        self.log_service = LogService(format=setting.LOG_FORMAT)
        self.wifi_service = WiFiService(
            setting.WIFI_SSID,
            setting.WIFI_PASSWORD,
            setting.WIFI_CONNECT_TIMEOUT_SECONDS,
        )
        self.registry = ServiceRegistry()
        self.watchdog_service = None
        if setting.WATCHDOG_ENABLED:
            self.watchdog_service = WatchdogService(setting.WATCHDOG_TIMEOUT_MS)
            self.registry.register("watchdog", start=self.watchdog_service.start)
        self.bootloop_guard = None
        if setting.BOOT_LOOP_PROTECTION_ENABLED:
            self.bootloop_guard = BootLoopGuard(
                setting.BOOT_LOOP_STATE_PATH, setting.BOOT_LOOP_MAX_ATTEMPTS
            )
        self.memory_monitor_service = None
        if setting.MEMORY_MONITOR_ENABLED:
            self.memory_monitor_service = MemoryMonitorService(
                setting.MEMORY_MONITOR_THRESHOLD_BYTES,
                setting.MEMORY_MONITOR_ACTION,
                logger=self.log_service,
            )
        self.health_check_service = None
        if setting.HEALTH_CHECK_ENABLED:
            self.health_check_service = HealthCheckService(
                interval_seconds=setting.HEALTH_CHECK_INTERVAL_SECONDS,
                logger=self.log_service,
            )
            self.health_check_service.register("wifi", self.wifi_service.is_connected)
            self.health_check_service.register("mqtt", lambda: self.client is not None)
        self.service_restart_service = None
        if setting.SERVICE_RESTART_ENABLED and self.health_check_service:
            self.service_restart_service = ServiceRestartService(
                max_attempts=setting.SERVICE_RESTART_MAX_ATTEMPTS
            )
            self.service_restart_service.register("wifi", self.wifi_service.connect)
            self.service_restart_service.register(
                "mqtt", lambda: self.connect_to_mqtt()
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
        self.registry.start_all()

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
                        if self.service_restart_service:
                            self.service_restart_service.reconcile(
                                self.health_check_service.status
                            )
                    self.client.check_msg()
                    time.sleep(1)
            except Exception as e:
                print("Connection lost:", e)
            finally:
                self.disconnect()
