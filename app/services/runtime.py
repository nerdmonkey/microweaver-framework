import gc
import time

try:
    import ujson as json
except ImportError:
    import json

from umqtt.simple import MQTTException

from app.adapters.payload import format_local_timestamp, to_payload
from app.adapters.sensors.potentiometer import PotentiometerAdapter
from app.adapters.sensors.rotary_angle import RotaryAngleAdapter
from app.services.bootloop import BootLoopGuard
from app.services.crash_log import CrashLogService
from app.services.device_cert import DeviceCertService
from app.services.error_handler import ErrorHandlerService, format_exception
from app.services.health import HealthCheckService
from app.services.logger import LogService
from app.services.memory_monitor import MemoryMonitorService
from app.services.metrics import MetricsService
from app.services.mqtt import MqttConnection
from app.services.ntp import NtpService
from app.services.ota import OtaService
from app.services.poll_scheduler import PollScheduler
from app.services.registry import ServiceRegistry
from app.services.service_restart import ServiceRestartService
from app.services.watchdog import WatchdogService
from app.services.wifi import WiFiService
from config.app import Setting

setting = (Setting()).get_settings()

# SUBACK return code for "Failure" (MQTT v3.1.1 section 3.9.3). The broker
# has explicitly refused the subscription (ACL/permissions), not a transient
# network blip - retrying the identical subscribe will keep failing, so this
# only gets a clearer log message, not special-cased retry logic.
SUBACK_FAILURE_RC = 128

# These adapters produce a slow-moving analog value; publish only when the
# reading actually moves instead of flooding the broker every poll tick.
CHANGE_ONLY_ADAPTER_TYPES = (PotentiometerAdapter, RotaryAngleAdapter)

# ESP32 ADC noise jitters read_u16() by tens of raw counts even with the
# wiper stationary, which is enough to flip the rounded-to-1-decimal percent
# every poll. An exact-equality change check would never suppress that, so
# treat readings within this many percentage points as "unchanged".
CHANGE_THRESHOLD_PERCENT = 1.0


class RuntimeService:
    def __init__(
        self,
        publish_adapters=None,
        subscribe_adapters=None,
        topics=None,
        topics_pub=None,
        topics_status=None,
        publish_intervals=None,
        unified_mode=False,
    ):
        self.topics_pub = (
            list(topics_pub) if topics_pub is not None else list(setting.MQTT_TOPIC_PUB)
        )
        self.topics = (
            list(topics) if topics is not None else list(setting.MQTT_TOPIC_SUB)
        )
        self.topics_status = dict(topics_status) if topics_status else {}
        self.unified_mode = bool(unified_mode)
        # In unified mode all adapters share MQTT_TOPIC_STATUS[0] instead of
        # a per-adapter status topic, so topics_status (a name->topic dict)
        # doesn't apply -- resolve the one shared state topic separately.
        self.unified_state_topic = self._resolve_unified_state_topic()
        self.dht_temperature_topic_suffix = setting.DHT_TEMPERATURE_TOPIC_SUFFIX
        self.dht_humidity_topic_suffix = setting.DHT_HUMIDITY_TOPIC_SUFFIX
        self.publish_qos = setting.MQTT_PUBLISH_QOS
        self.publish_retain = setting.MQTT_PUBLISH_RETAIN
        self.ota_status_topic = setting.OTA_STATUS_TOPIC
        self.message_handlers = {}
        self.watchdog_service = None
        if setting.WATCHDOG_ENABLED:
            self.watchdog_service = WatchdogService(setting.WATCHDOG_TIMEOUT_MS)
        wifi_static_ip = self._resolve_wifi_static_ip()
        # network.WLAN() needs one contiguous internal-DRAM block for its rx/tx
        # buffers, so grab it before the log/crash-log/metrics/error-handler
        # objects below churn and fragment the heap. gc.collect() here prevents
        # esp-idf's "Expected to init 10 rx buffer, actual is 2" OOM at
        # construction time.
        gc.collect()
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
        self.log_service = LogService(
            format=setting.LOG_FORMAT, level=setting.LOG_LEVEL
        )
        self.crash_log = CrashLogService(
            setting.CRASH_LOG_PATH,
            setting.CRASH_LOG_ENABLED,
            max_bytes=setting.CRASH_LOG_MAX_BYTES,
        )
        self.metrics_service = MetricsService()
        self.error_handler = ErrorHandlerService(
            logger=self.log_service,
            crash_log=self.crash_log,
            metrics=self.metrics_service,
        )
        self.registry = ServiceRegistry(error_handler=self.error_handler)
        if self.watchdog_service:
            self.registry.register("watchdog", start=self.watchdog_service.start)
        self.publish_adapters = list(publish_adapters) if publish_adapters else []
        self.publish_intervals = dict(publish_intervals) if publish_intervals else {}
        self.subscribe_adapters = list(subscribe_adapters) if subscribe_adapters else []
        self.subscribe_adapter_map = dict(self.subscribe_adapters)
        self._subscribe_adapter_names = {
            id(adapter): name for name, adapter in self.subscribe_adapters
        }
        self.publish_scheduler = PollScheduler(interval_seconds=1)
        self._last_published_readings = {}
        self._register_adapters()
        self._register_command_handlers()
        self._init_log_level_override()
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
        self.device_cert_service = DeviceCertService(
            setting.DEVICE_CERT_PATH, setting.DEVICE_KEY_PATH
        )
        self._init_ntp_service()
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
            self.ntp_service,
            self.device_cert_service,
            setting.DEVICE_CERT,
            setting.DEVICE_KEY,
        )
        self.client = None
        self._reconnect_delay_seconds = setting.MQTT_RECONNECT_DELAY_SECONDS
        self._max_reconnect_delay_seconds = setting.MQTT_MAX_RECONNECT_DELAY_SECONDS
        self.registry.start_all()

    def _resolve_unified_state_topic(self):
        if self.unified_mode and setting.MQTT_TOPIC_STATUS:
            return list(setting.MQTT_TOPIC_STATUS)[0]
        return None

    def _resolve_wifi_static_ip(self):
        if (
            setting.WIFI_IP
            and setting.WIFI_SUBNET
            and setting.WIFI_GATEWAY
            and setting.WIFI_DNS
        ):
            return (
                setting.WIFI_IP,
                setting.WIFI_SUBNET,
                setting.WIFI_GATEWAY,
                setting.WIFI_DNS,
            )
        return None

    def _register_adapters(self):
        for name, adapter in self.publish_adapters + self.subscribe_adapters:
            self.registry.register_adapter(name, adapter)
            if (name, adapter) in self.publish_adapters:
                self.publish_scheduler.register(name, self.publish_intervals.get(name))

    def _register_command_handlers(self):
        for topic in self.topics:
            self.message_handlers[topic] = self._handle_command_message

    def _init_ntp_service(self):
        self.ntp_service = None
        if setting.NTP_ENABLED:
            self.ntp_service = NtpService(
                setting.NTP_HOST,
                setting.NTP_SYNC_ATTEMPTS,
                setting.NTP_RETRY_DELAY_SECONDS,
            )

    def _init_log_level_override(self):
        if setting.LOG_LEVEL_OVERRIDE_ENABLED and setting.LOG_LEVEL_TOPIC:
            self.topics.append(setting.LOG_LEVEL_TOPIC)
            self.message_handlers[
                setting.LOG_LEVEL_TOPIC
            ] = self._handle_log_level_message

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

    def publish_message(self, topic, message):
        self._publish(topic, message)

    def _resolve_publish_topic(self, name):
        """Mirrors _resolve_command_adapter's routing, inverted: given a
        publish adapter's name, pick which configured mqtt_topic_pub entry
        it publishes to. A single configured topic is shared by every
        publish adapter (backward compatible with the pre-list default);
        with more than one, match by exact topic or topic-suffix == name."""
        if len(self.topics_pub) == 1:
            return self.topics_pub[0]
        for topic in self.topics_pub:
            if topic == name or topic.rsplit("/", 1)[-1] == name:
                return topic
        return None

    def connect_to_mqtt(self):
        self.client = self.connection.connect()
        self.client.set_callback(self.on_message)
        for topic in self.topics:
            print("Subscribing to topic:", topic)
            self._subscribe(topic)
            print("Subscribed to topic:", topic)

    def _subscribe(self, topic):
        try:
            self.client.subscribe(topic)
        except MQTTException as e:
            rc = e.args[0] if e.args else None
            if rc == SUBACK_FAILURE_RC:
                raise MQTTException(
                    "subscribe_refused: broker denied topic '{}' (rc={}) "
                    "- check ACL/permissions".format(topic, rc)
                )
            raise

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

    def _handle_log_level_message(self, topic, message):
        requested = message.decode().strip().lower()
        if self.log_service.set_level(requested):
            self.log_service.log(
                "log_level_overridden", level="info", new_level=requested
            )
        else:
            self.log_service.log(
                "log_level_override_rejected", level="warning", requested=requested
            )

    def _handle_command_message(self, topic, message):
        if self.unified_mode:
            self._handle_unified_command_message(message)
            return
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
            return
        self._publish_status(adapter)

    def _handle_unified_command_message(self, message):
        """Unified contract: one shared command topic, JSON object keyed by
        subscribe adapter name. Each key's value is either a bare verb
        string ("on"/"off"/"toggle") or {"command": "<adapter method>",
        ...params} for structured commands (e.g. RGB set(color, brightness)).
        A "request_id" key is metadata, not a component -- always skipped."""
        try:
            payload = json.loads(message.decode())
        except Exception:
            print("Invalid unified command payload:", message)
            return
        if not isinstance(payload, dict):
            print("Unified command payload must be a JSON object:", message)
            return
        changed = {}
        for name, value in payload.items():
            if name == "request_id":
                continue
            adapter = self.subscribe_adapter_map.get(name)
            if not adapter:
                print("No subscribe adapter matched for unified command key:", name)
                continue
            if self._apply_unified_command(adapter, value):
                state_value = self._adapter_state_value(adapter)
                if state_value is not None:
                    changed[name] = state_value
        if changed:
            self._publish_unified_state(changed)

    def _adapter_state_value(self, adapter):
        """Some actuators report richer state than a plain on/off boolean:
        state() for structured status (e.g. RGB's {"color":..., "brightness":...}
        or "off"), direction() for a 2-pin DC motor driver's "cw"/"ccw"/"stop".
        Prefer the most specific one available, falling back to on/off."""
        if hasattr(adapter, "state"):
            return adapter.state()
        if hasattr(adapter, "direction"):
            return adapter.direction()
        if hasattr(adapter, "is_on"):
            return "on" if adapter.is_on() else "off"
        return None

    def _apply_unified_command(self, adapter, value):
        if isinstance(value, dict):
            command = value.get("command")
            if not command or not hasattr(adapter, command):
                print("Unsupported unified command:", value)
                return False
            params = dict(value)
            del params["command"]
            getattr(adapter, command)(**params)
            return True
        command = str(value).strip().lower()
        if command == "on":
            adapter.on()
        elif command == "off":
            adapter.off()
        elif command == "toggle":
            adapter.toggle()
        elif hasattr(adapter, command):
            # Bare verb with no params (e.g. "clear") -- call the matching
            # no-arg adapter method directly, same as the structured
            # {"command": "<method>"} form but without params to strip.
            getattr(adapter, command)()
        else:
            print("Unsupported unified command:", value)
            return False
        return True

    def _publish_unified_state(self, changed):
        if not self.unified_state_topic:
            return
        self.publish_message(self.unified_state_topic, json.dumps(changed))

    def _publish_status(self, adapter):
        name = self._subscribe_adapter_names.get(id(adapter))
        topic = self.topics_status.get(name)
        if not topic or not hasattr(adapter, "is_on"):
            return
        self.publish_message(
            topic,
            self._envelope(
                "state_report", {"state": self._adapter_state_value(adapter)}
            ),
        )

    def _resolve_command_adapter(self, topic):
        if topic in self.subscribe_adapter_map:
            return self.subscribe_adapter_map[topic]
        topic_name = topic.rsplit("/", 1)[-1]
        if topic_name in self.subscribe_adapter_map:
            return self.subscribe_adapter_map[topic_name]
        if len(self.subscribe_adapter_map) == 1:
            return next(iter(self.subscribe_adapter_map.values()))
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
        if self.unified_mode:
            self._poll_unified_publish_adapters()
            return
        for name, adapter in self.publish_adapters:
            reading = self.publish_scheduler.poll(name, adapter.read)
            if reading is None:
                continue
            if isinstance(adapter, CHANGE_ONLY_ADAPTER_TYPES):
                last = self._last_published_readings.get(name)
                if last is not None and abs(reading - last) < CHANGE_THRESHOLD_PERCENT:
                    continue
                self._last_published_readings[name] = reading
            if self._is_dual_reading(adapter, reading):
                self._publish_dual_reading(reading)
                continue
            payload = self._to_publish_payload(name, adapter, reading)
            if payload is None:
                continue
            topic = self._resolve_publish_topic(name)
            if topic is None:
                print("No publish topic matched for adapter:", name)
                continue
            self.publish_message(topic, payload)

    def _is_dual_reading(self, adapter, reading):
        return (
            isinstance(reading, (list, tuple))
            and len(reading) == 2
            and hasattr(adapter, "temperature")
            and hasattr(adapter, "humidity")
        )

    def _publish_dual_reading(self, reading):
        """DHT-shaped (temperature, humidity) readings publish as two
        separate messages, one per measurement, instead of one combined
        payload - each measurement gets its own topic
        (dht_temperature_topic_suffix/dht_humidity_topic_suffix)."""
        temperature, humidity = reading
        for suffix, value in (
            (self.dht_temperature_topic_suffix, temperature),
            (self.dht_humidity_topic_suffix, humidity),
        ):
            topic = self._resolve_publish_topic(suffix)
            if topic is None:
                print("No publish topic matched for adapter:", suffix)
                continue
            self.publish_message(
                topic, self._envelope("sensor_reading", {"value": value})
            )

    def _poll_unified_publish_adapters(self):
        """Unified contract: every publish adapter's reading (that's due
        this tick and passed the change-only check) merges into ONE flat
        JSON object, keyed by adapter name, published once to the shared
        MQTT_TOPIC_PUB[0] topic -- no per-adapter topic, no envelope."""
        batch = {}
        for name, adapter in self.publish_adapters:
            reading = self.publish_scheduler.poll(name, adapter.read)
            if reading is None:
                continue
            if isinstance(adapter, CHANGE_ONLY_ADAPTER_TYPES):
                last = self._last_published_readings.get(name)
                if last is not None and abs(reading - last) < CHANGE_THRESHOLD_PERCENT:
                    continue
                self._last_published_readings[name] = reading
            self._merge_unified_reading(batch, name, adapter, reading)
        if not batch:
            return
        topic = self.topics_pub[0] if self.topics_pub else None
        if topic is None:
            print("No unified publish topic configured")
            return
        self.publish_message(topic, json.dumps(batch))

    def _merge_unified_reading(self, batch, name, adapter, reading):
        if self._is_dual_reading(adapter, reading):
            temperature, humidity = reading
            batch[self.dht_temperature_topic_suffix] = temperature
            batch[self.dht_humidity_topic_suffix] = humidity
        elif isinstance(reading, dict):
            batch.update(reading)
        elif isinstance(reading, bool):
            batch[name] = "on" if reading else "off"
        elif isinstance(reading, (int, float, str)):
            batch[name] = reading
        else:
            print("Unsupported publish payload from adapter:", name)

    def _to_publish_payload(self, name, adapter, reading):
        if isinstance(reading, dict):
            return self._envelope("sensor_reading", reading)
        if isinstance(reading, bool):
            return self._envelope("state_report", {"state": "on" if reading else "off"})
        if isinstance(reading, (int, float, str)):
            return self._envelope("sensor_reading", {"value": reading})
        print("Unsupported publish payload from adapter:", name)
        return None

    def _envelope(self, action, fields):
        now = time.time()
        envelope = {"action": action, "client_id": setting.MQTT_CLIENT_ID}
        envelope.update(fields)
        envelope["ok"] = True
        envelope["timestamp"] = now
        envelope["timestamp_local"] = format_local_timestamp(
            now, setting.TIMEZONE_OFFSET_MINUTES
        )
        envelope["device"] = setting.DEVICE_NAME
        envelope["timezone"] = setting.TIMEZONE
        return to_payload(**envelope)

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
        delay = self._reconnect_delay_seconds
        while True:
            try:
                if setting.MQTT_ENABLED:
                    self.connect_to_mqtt()
                delay = self._reconnect_delay_seconds
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
                if setting.MQTT_ENABLED:
                    time.sleep(delay)
                    delay = min(delay * 2, self._max_reconnect_delay_seconds)
            finally:
                self.disconnect()
