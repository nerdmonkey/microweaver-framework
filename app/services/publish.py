import time

from app.services.bootloop import BootLoopGuard
from app.services.error_handler import ErrorHandlerService
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


class PublishService:
    def __init__(self, adapters=None):
        self.topic = setting.MQTT_TOPIC_PUB
        self.publish_qos = setting.MQTT_PUBLISH_QOS
        self.publish_retain = setting.MQTT_PUBLISH_RETAIN
        self.log_service = LogService(format=setting.LOG_FORMAT)
        self.error_handler = ErrorHandlerService(logger=self.log_service)
        self.watchdog_service = None
        if setting.WATCHDOG_ENABLED:
            self.watchdog_service = WatchdogService(setting.WATCHDOG_TIMEOUT_MS)
        wifi_static_ip = None
        if (
            setting.WIFI_IP
            and setting.WIFI_SUBNET
            and setting.WIFI_GATEWAY
            and setting.WIFI_DNS
        ):
            wifi_static_ip = (
                setting.WIFI_IP,
                setting.WIFI_SUBNET,
                setting.WIFI_GATEWAY,
                setting.WIFI_DNS,
            )
        self.wifi_service = WiFiService(
            setting.WIFI_SSID,
            setting.WIFI_PASSWORD,
            setting.WIFI_CONNECT_TIMEOUT_SECONDS,
            setting.WIFI_RECONNECT_DELAY_SECONDS,
            setting.WIFI_MAX_RECONNECT_DELAY_SECONDS,
            self.watchdog_service,
            wifi_static_ip,
            setting.WIFI_DISABLE_POWER_SAVE,
        )
        self.registry = ServiceRegistry(error_handler=self.error_handler)
        if self.watchdog_service:
            self.registry.register("watchdog", start=self.watchdog_service.start)
        self.adapters = list(adapters) if adapters else []
        self._register_adapters()
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
        self._init_health_check()
        self._init_service_restart()
        ssl_params = {}
        if setting.MQTT_SSL_CERT_PATH:
            ssl_params["cert"] = setting.MQTT_SSL_CERT_PATH
        if setting.MQTT_SSL_KEY_PATH:
            ssl_params["key"] = setting.MQTT_SSL_KEY_PATH
        self.connection = MqttConnection(
            setting.MQTT_CLIENT_ID,
            setting.MQTT_BROKER,
            setting.MQTT_PORT,
            self.wifi_service,
            setting.MQTT_RECONNECT_DELAY_SECONDS,
            setting.MQTT_MAX_RECONNECT_DELAY_SECONDS,
            setting.MQTT_KEEPALIVE_SECONDS,
            self.watchdog_service,
            setting.MQTT_USERNAME,
            setting.MQTT_PASSWORD,
            setting.MQTT_SSL,
            ssl_params or None,
            setting.MQTT_LWT_TOPIC or None,
            setting.MQTT_LWT_MESSAGE or None,
            setting.MQTT_LWT_RETAIN,
            setting.MQTT_LWT_QOS,
        )
        self.client = None
        self.registry.start_all()

    def _register_adapters(self):
        for name, adapter in self.adapters:
            self.registry.register_adapter(name, adapter)

    def _init_health_check(self):
        self.health_check_service = None
        if setting.HEALTH_CHECK_ENABLED:
            self.health_check_service = HealthCheckService(
                interval_seconds=setting.HEALTH_CHECK_INTERVAL_SECONDS,
                logger=self.log_service,
            )
            self.health_check_service.register("wifi", self.wifi_service.is_connected)
            if setting.MQTT_ENABLED:
                self.health_check_service.register(
                    "mqtt", lambda: self.client is not None
                )

    def _init_service_restart(self):
        self.service_restart_service = None
        if setting.SERVICE_RESTART_ENABLED and self.health_check_service:
            self.service_restart_service = ServiceRestartService(
                max_attempts=setting.SERVICE_RESTART_MAX_ATTEMPTS
            )
            self.service_restart_service.register("wifi", self.wifi_service.connect)
            if setting.MQTT_ENABLED:
                self.service_restart_service.register(
                    "mqtt", lambda: self.connect_to_mqtt()
                )

    def connect_to_mqtt(self):
        self.client = self.connection.connect()

    def publish_message(self, message):
        if self.client:
            try:
                print("Publishing message to topic:", self.topic)
                self.client.publish(
                    self.topic,
                    message.encode(),
                    qos=self.publish_qos,
                    retain=self.publish_retain,
                )
                print("Message published")
            except Exception as e:
                print("Failed to publish message:", e)
        else:
            print("Not connected to MQTT.")

    def disconnect(self):
        self.connection.disconnect()
        self.client = None

    def stop(self):
        self.registry.stop_all()

    def _run_tick(self, message):
        if self.watchdog_service:
            self.watchdog_service.feed()
        self.wifi_service.ensure_connected()
        if self.memory_monitor_service:
            self.error_handler.guard(
                self.memory_monitor_service.check, "memory_monitor"
            )
        if self.health_check_service:
            self.health_check_service.poll()
            if self.service_restart_service:
                self.service_restart_service.reconcile(self.health_check_service.status)
        if setting.MQTT_ENABLED:
            self.publish_message(message)

    def run(self, message="Hello from Agnes agent"):
        while True:
            if setting.MQTT_ENABLED:
                self.connect_to_mqtt()
            if self.bootloop_guard:
                self.bootloop_guard.confirm()
            try:
                while True:
                    self._run_tick(message)
                    time.sleep(1)
            except Exception as e:
                print("Connection lost:", e)
            finally:
                self.disconnect()
