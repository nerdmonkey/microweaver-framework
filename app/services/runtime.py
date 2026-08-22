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
    ):
        # Unified per-device envelope, derived from the MQTT username (which is
        # the device_id the backend authenticates the client as -- matches
        # devices/{credential.username}/... on the Agnes side). topics/topics_pub
        # remain accepted for explicit override/back-compat, but default to this
        # single set of topics rather than the old per-adapter-suffix lists.
        self.topic_data = "devices/{}/data".format(setting.MQTT_USERNAME)
        self.topic_command = "devices/{}/command".format(setting.MQTT_USERNAME)
        self.topic_state = "devices/{}/state".format(setting.MQTT_USERNAME)
        self.topic_availability = "devices/{}/availability".format(
            setting.MQTT_USERNAME
        )

        self.topics_pub = (
            list(topics_pub) if topics_pub is not None else [self.topic_data]
        )
        self.topics = (
            list(topics)
            if topics is not None
            else ([self.topic_command] if subscribe_adapters else [])
        )
        # topics_status is no longer used (superseded by the merged topic_state
        # publish) -- kept as an accepted-but-ignored constructor arg for
        # back-compat with older call sites.
        self.dht_temperature_topic_suffix = setting.DHT_TEMPERATURE_TOPIC_SUFFIX
        self.dht_humidity_topic_suffix = setting.DHT_HUMIDITY_TOPIC_SUFFIX
        self.publish_qos = setting.MQTT_PUBLISH_QOS
        self.publish_retain = setting.MQTT_PUBLISH_RETAIN
        self.ota_status_topic = setting.OTA_STATUS_TOPIC
        self.message_handlers = {}
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
        self.subscribe_adapters = list(subscribe_adapters) if subscribe_adapters else []
        self.subscribe_adapter_map = dict(self.subscribe_adapters)
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
        self._init_state_report()
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

    def _register_adapters(self):
        for name, adapter in self.publish_adapters + self.subscribe_adapters:
            self.registry.register_adapter(name, adapter)
            if (name, adapter) in self.publish_adapters:
                self.publish_scheduler.register(name)

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

    def _init_state_report(self):
        self.state_report_scheduler = None
        if setting.MQTT_ENABLED and self.subscribe_adapters:
            self.state_report_scheduler = PollScheduler(
                setting.STATE_REPORT_INTERVAL_SECONDS
            )
            self.state_report_scheduler.register("state_report")

    def _report_ota_status(self, payload):
        payload.setdefault("app_version", setting.APP_VERSION)
        self._publish(self.ota_status_topic, json.dumps(payload))

    def _publish(self, topic, message, retain=None):
        if self.client:
            try:
                print("Publishing message to topic:", topic)
                self.client.publish(
                    topic,
                    message.encode(),
                    qos=self.publish_qos,
                    retain=self.publish_retain if retain is None else retain,
                )
                print("Message published")
                self.metrics_service.record_publish()
            except Exception as e:
                print("Failed to publish message:", e)
                self.metrics_service.record_error()
        else:
            print("Not connected to MQTT.")

    def publish_message(self, topic, message, retain=None):
        self._publish(topic, message, retain=retain)

    def connect_to_mqtt(self):
        self.client = self.connection.connect()
        self.client.set_callback(self.on_message)
        # Birth message: mirrors the LWT's offline payload so the backend can
        # tell "never connected"/"cleanly reconnected" apart from a stale LWT.
        # Always retained regardless of MQTT_PUBLISH_RETAIN, matching the LWT's
        # own retain semantics.
        self._publish(
            self.topic_availability, json.dumps({"state": "online"}), retain=True
        )
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
        handler = self.message_handlers.get(topic_name, self._default_handler)
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
        """Unified devices/{id}/command contract: a flat multi-key JSON
        payload, routed by JSON key against subscribe_adapter_map (adapter
        name) -- e.g. {"relay_1":"on","led_1":"off"} commands both adapters
        from one message. A single-adapter device also accepts a bare
        command (non-JSON, or a JSON dict/value whose keys don't match any
        adapter name) as shorthand for that one adapter, so single-adapter
        setups keep working without needing to know their own adapter name."""
        raw = message.decode()
        data = self._parse_command_json(raw)
        matched = self._match_command_targets(data, raw)

        if not matched:
            self._default_handler(topic, message)
            return

        commanded = False
        for adapter, value in matched:
            if self._apply_command(adapter, value):
                commanded = True
        if commanded:
            self._publish_state()

    def _parse_command_json(self, raw):
        try:
            return json.loads(raw)
        except Exception:
            return None

    def _match_command_targets(self, data, raw):
        matched = []
        if isinstance(data, dict):
            for key, value in data.items():
                if key == "request_id":
                    continue
                adapter = self.subscribe_adapter_map.get(key)
                if adapter is not None:
                    matched.append((adapter, value))

        if not matched and len(self.subscribe_adapter_map) == 1:
            only_adapter = next(iter(self.subscribe_adapter_map.values()))
            matched = [(only_adapter, data if data is not None else raw)]

        return matched

    def _apply_command(self, adapter, value):
        """Structured {"command": <adapter-method-name>, ...params} values
        (e.g. {"command":"set","color":{"r":255,"g":0,"b":0},"brightness":128})
        dispatch to that named method on the adapter with the remaining keys
        as kwargs. Everything else (bare "on"/"off"/"toggle", or a legacy
        {"state":...}/{"value":...} dict) goes through the simple on/off/
        toggle verb path."""
        if isinstance(value, dict) and "command" in value:
            return self._apply_structured_command(adapter, value)

        command = self._decode_command_value(value)
        if command == "on":
            adapter.on()
        elif command == "off":
            adapter.off()
        elif command == "toggle":
            adapter.toggle()
        else:
            print("Unsupported command:", command)
            return False
        return True

    def _apply_structured_command(self, adapter, value):
        command_name = value.get("command")
        if (
            not isinstance(command_name, str)
            or not command_name
            or command_name.startswith("_")
        ):
            print("Unsupported structured command:", command_name)
            return False
        if command_name in ("setup", "deinit"):
            print("Refusing to dispatch lifecycle method as a command:", command_name)
            return False
        method = getattr(adapter, command_name, None)
        if not callable(method):
            print("Unsupported structured command:", command_name)
            return False
        params = {k: v for k, v in value.items() if k != "command"}
        try:
            method(**params)
        except TypeError as e:
            print("Bad params for command", command_name, "-", e)
            return False
        return True

    def _publish_state(self):
        """Merged devices/{id}/state snapshot. Adapters with a state() method
        (RGB color+brightness, LED brightness, ...) report their real
        parameters; simple binary adapters (relay, ...) fall back to
        is_on()'s "on"/"off"."""
        state = {}
        for name, adapter in self.subscribe_adapters:
            if hasattr(adapter, "state"):
                state[name] = adapter.state()
            elif hasattr(adapter, "is_on"):
                state[name] = "on" if adapter.is_on() else "off"
        if state:
            self.publish_message(self.topic_state, json.dumps(state))

    def _decode_command_value(self, value):
        if isinstance(value, dict):
            value = value.get("state", value.get("command", value.get("value")))
        if isinstance(value, bool):
            return "on" if value else "off"
        return str(value).strip().lower()

    def _poll_publish_adapters(self):
        """Unified devices/{id}/data contract: every enabled publish adapter's
        latest reading is collected into one flat dict, keyed by adapter name
        (DHT's dual reading contributes two keys via its topic-suffix config,
        repurposed as JSON key names), and published as a single message per
        tick -- instead of the old one-publish-per-adapter-per-topic loop."""
        merged = {}
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
                temperature, humidity = reading
                merged[self.dht_temperature_topic_suffix] = temperature
                merged[self.dht_humidity_topic_suffix] = humidity
                continue
            value = self._to_publish_value(name, adapter, reading)
            if value is None:
                continue
            merged[name] = value
        if merged:
            self.publish_message(self.topics_pub[0], json.dumps(merged))

    def _is_dual_reading(self, adapter, reading):
        return (
            isinstance(reading, (list, tuple))
            and len(reading) == 2
            and hasattr(adapter, "temperature")
            and hasattr(adapter, "humidity")
        )

    def _to_publish_value(self, name, adapter, reading):
        if isinstance(reading, dict):
            return reading
        if isinstance(reading, bool):
            return "on" if reading else "off"
        if isinstance(reading, (int, float, str)):
            return reading
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
            if self.state_report_scheduler:
                self.state_report_scheduler.poll("state_report", self._publish_state)
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
