import time

try:
    import ujson as json
except ImportError:
    import json

from app.adapters.payload import to_payload
from app.services.bootloop import BootLoopGuard
from app.services.crash_log import CrashLogService
from app.services.error_handler import ErrorHandlerService, format_exception
from app.services.health import HealthCheckService
from app.services.logger import LogService
from app.services.memory_monitor import MemoryMonitorService
from app.services.metrics import MetricsService
from app.services.mqtt import MqttConnection
from app.services.ota import OtaService
from app.services.poll_scheduler import PollScheduler
from app.services.registry import ServiceRegistry
from app.services.service_restart import ServiceRestartService
from app.services.watchdog import WatchdogService
from app.services.wifi import WiFiService
from config.app import Setting

setting = (Setting()).get_settings()


class RuntimeService:
    def __init__(self, publish_adapters=None, command_adapters=None):
        self.topic = setting.MQTT_TOPIC_PUB
        self.topics = list(setting.MQTT_TOPIC_SUB)
        self.publish_qos = setting.MQTT_PUBLISH_QOS
        self.publish_retain = setting.MQTT_PUBLISH_RETAIN
        self.ota_status_topic = setting.OTA_STATUS_TOPIC
        self.message_handlers = {}
        self.log_service = LogService(
            format=setting.LOG_FORMAT, level=setting.LOG_LEVEL
        )
        self.crash_log = CrashLogService(
            setting.CRASH_LOG_PATH, setting.CRASH_LOG_ENABLED
        )
        self.metrics_service = MetricsService()
        self.error_handler = ErrorHandlerService(
            logger=self.log_service,
            crash_log=self.crash_log,
            metrics=self.metrics_service,
        )
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
        self.publish_adapters = list(publish_adapters) if publish_adapters else []
        self.command_adapters = list(command_adapters) if command_adapters else []
        self.command_adapter_map = dict(self.command_adapters)
        self.publish_scheduler = PollScheduler(interval_seconds=1)
        self._register_adapters()
        self._register_command_handlers()
        self.bootloop_guard = None
        if setting.BOOT_LOOP_PROTECTION_ENABLED:
            self.bootloop_guard = BootLoopGuard(
                setting.BOOT_LOOP_STATE_PATH, setting.BOOT_LOOP_MAX_ATTEMPTS
            )
        self.ota_service = None
        if setting.OTA_ENABLED:
            self.ota_service = OtaService(
                setting.OTA_MANIFEST_URL,
                setting=setting,
                state_path=setting.OTA_STATE_PATH,
                on_status=self._report_ota_status,
            )
            if setting.OTA_TOPIC:
                self.topics.append(setting.OTA_TOPIC)
                self.message_handlers[setting.OTA_TOPIC] = self._handle_ota_message
        self.memory_monitor_service = None
        if setting.MEMORY_MONITOR_ENABLED:
            self.memory_monitor_service = MemoryMonitorService(
                setting.MEMORY_MONITOR_THRESHOLD_BYTES,
                setting.MEMORY_MONITOR_ACTION,
                logger=self.log_service,
                crash_log=self.crash_log,
            )
        self._init_health_check()
        self._init_service_restart()
        self._init_health_report()
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
        for name, adapter in self.publish_adapters + self.command_adapters:
            self.registry.register_adapter(name, adapter)
            if (name, adapter) in self.publish_adapters:
                self.publish_scheduler.register(name)

    def _register_command_handlers(self):
        for topic in self.topics:
            self.message_handlers[topic] = self._handle_command_message

    def _init_health_check(self):
        self.health_check_service = None
        if setting.HEALTH_CHECK_ENABLED:
            self.health_check_service = HealthCheckService(
                interval_seconds=setting.HEALTH_CHECK_INTERVAL_SECONDS,
                logger=self.log_service,
                app_version=setting.APP_VERSION,
                metrics=self.metrics_service,
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

    def _init_health_report(self):
        self.health_report_topic = setting.HEALTH_REPORT_TOPIC
        self.health_report_scheduler = None
        if (
            setting.HEALTH_REPORT_ENABLED
            and setting.MQTT_ENABLED
            and self.health_check_service
        ):
            self.health_report_scheduler = PollScheduler(
                setting.HEALTH_REPORT_INTERVAL_SECONDS
            )
            self.health_report_scheduler.register("health_report")

    def _publish_health_report(self):
        self._publish(
            self.health_report_topic, json.dumps(self.health_check_service.report())
        )

    def _report_ota_status(self, payload):
        payload.setdefault("app_version", setting.APP_VERSION)
        self._publish(self.ota_status_topic, json.dumps(payload))

    def _publish(self, topic, message):
        if self.client:
            try:
                print("Publishing message to topic:", topic)
                self.client.publish(
                    topic,
                    message.encode(),
                    qos=self.publish_qos,
                    retain=self.publish_retain,
                )
                print("Message published")
                self.metrics_service.record_publish()
            except Exception as e:
                print("Failed to publish message:", e)
                self.metrics_service.record_error()
        else:
            print("Not connected to MQTT.")

    def publish_message(self, message):
        self._publish(self.topic, message)

    def connect_to_mqtt(self):
        self.client = self.connection.connect()
        self.client.set_callback(self.on_message)
        for topic in self.topics:
            print("Subscribing to topic:", topic)
            self.client.subscribe(topic)
            print("Subscribed to topic:", topic)

    def disconnect(self):
        self.connection.disconnect()
        self.client = None

    def stop(self):
        self.registry.stop_all()

    def on_message(self, topic, message):
        self.metrics_service.record_message()
        topic_name = topic.decode()
        handler = self.message_handlers.get(topic_name)
        if not handler and self._resolve_command_adapter(topic_name):
            handler = self._handle_command_message
        if not handler:
            handler = self._default_handler
        handler(topic, message)

    def _default_handler(self, topic, message):
        print("Received message on topic:", topic.decode(), "-", message.decode())

    def _handle_ota_message(self, topic, message):
        print("OTA update triggered via MQTT:", message.decode())
        self.error_handler.guard(self.ota_service.apply_update, "ota_update")

    def _handle_command_message(self, topic, message):
        adapter = self._resolve_command_adapter(topic.decode())
        if not adapter:
            self._default_handler(topic, message)
            return
        command = self._decode_command(message)
        if command == "on":
            adapter.on()
        elif command == "off":
            adapter.off()
        elif command == "toggle":
            adapter.toggle()
        else:
            print("Unsupported command for topic:", topic.decode(), "-", command)

    def _resolve_command_adapter(self, topic):
        if topic in self.command_adapter_map:
            return self.command_adapter_map[topic]
        topic_name = topic.rsplit("/", 1)[-1]
        if topic_name in self.command_adapter_map:
            return self.command_adapter_map[topic_name]
        if len(self.command_adapter_map) == 1:
            return next(iter(self.command_adapter_map.values()))
        return None

    def _decode_command(self, message):
        payload = message.decode().strip()
        try:
            value = json.loads(payload)
        except Exception:
            value = payload
        if isinstance(value, dict):
            value = value.get("state", value.get("command", value.get("value")))
        if isinstance(value, bool):
            return "on" if value else "off"
        return str(value).strip().lower()

    def _poll_publish_adapters(self):
        for name, adapter in self.publish_adapters:
            reading = self.publish_scheduler.poll(name, adapter.read)
            if reading is None:
                continue
            payload = self._to_publish_payload(name, adapter, reading)
            if payload is not None:
                self.publish_message(payload)

    def _to_publish_payload(self, name, adapter, reading):
        if isinstance(reading, dict):
            return to_payload(**reading)
        if (
            isinstance(reading, (list, tuple))
            and len(reading) == 2
            and hasattr(adapter, "temperature")
            and hasattr(adapter, "humidity")
        ):
            return to_payload(temperature=reading[0], humidity=reading[1])
        if isinstance(reading, bool):
            return to_payload(state="on" if reading else "off")
        if isinstance(reading, (int, float, str)):
            return to_payload(value=reading)
        print("Unsupported publish payload from adapter:", name)
        return None

    def _run_tick(self):
        self.log_service.log(
            "tick", level="debug", wifi_connected=self.wifi_service.is_connected()
        )
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
            if self.health_report_scheduler:
                self.health_report_scheduler.poll(
                    "health_report", self._publish_health_report
                )
        if setting.MQTT_ENABLED:
            self._poll_publish_adapters()
            self.client.check_msg()

    def run(self):
        while True:
            try:
                if setting.MQTT_ENABLED:
                    self.connect_to_mqtt()
                if self.bootloop_guard:
                    self.bootloop_guard.confirm()
                if self.ota_service:
                    self.ota_service.confirm_update()
                while True:
                    self._run_tick()
                    time.sleep(1)
            except Exception as e:
                self.log_service.log(
                    "connection_lost",
                    level="error",
                    error=str(e),
                    trace=format_exception(e),
                )
                self.metrics_service.record_error()
            finally:
                self.disconnect()
