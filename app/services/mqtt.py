import time

from umqtt.simple import MQTTClient, MQTTException

# CONNACK return codes. rc=3 (server unavailable) is transient - the broker
# itself is down/overloaded and may recover, so it gets the normal
# exponential-backoff retry. rc=1/2/4/5 are permanent for a given
# config/credentials - the broker has explicitly rejected this client and
# retrying every few seconds will never succeed, only hammer the broker.
PERMANENT_REJECTIONS = {
    1: "unacceptable_protocol_version",
    2: "client_identifier_rejected",
    4: "bad_username_or_password",
    5: "not_authorized",
}
TRANSIENT_REJECTIONS = {
    3: "server_unavailable",
}


class MqttConnectionRejected(Exception):
    def __init__(self, rc, reason):
        self.rc = rc
        self.reason = reason
        super().__init__("MQTT connection rejected: {} (rc={})".format(reason, rc))


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
        ssl=False,
        ssl_params=None,
        lwt_topic=None,
        lwt_message=None,
        lwt_retain=False,
        lwt_qos=0,
        ntp_service=None,
        device_cert_service=None,
        device_cert=None,
        device_key=None,
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
        self.ssl = ssl
        self.ssl_params = ssl_params
        self.lwt_topic = lwt_topic
        self.lwt_message = lwt_message
        self.lwt_retain = lwt_retain
        self.lwt_qos = lwt_qos
        self.ntp_service = ntp_service
        self.device_cert_service = device_cert_service
        self.device_cert = device_cert
        self.device_key = device_key
        self.client = None

    def _client_kwargs(self):
        client_kwargs = {"keepalive": self.keepalive_seconds}
        if self.username:
            client_kwargs["user"] = self.username
            client_kwargs["password"] = self.password
        if self.ssl:
            client_kwargs["ssl"] = True
            if self.ssl_params:
                client_kwargs["ssl_params"] = self.ssl_params
        return client_kwargs

    def _apply_last_will(self):
        if self.lwt_topic:
            self.client.set_last_will(
                self.lwt_topic,
                self.lwt_message,
                retain=self.lwt_retain,
                qos=self.lwt_qos,
            )

    @staticmethod
    def _connack_rc(exc):
        try:
            return exc.args[0]
        except (IndexError, TypeError):
            return None

    def connect(self):
        if not self.wifi_service.is_connected():
            self.wifi_service.connect()

        if self.ssl and self.ntp_service:
            self.ntp_service.sync()

        if self.ssl and not self.ssl_params and self.device_cert_service:
            self.ssl_params = (
                self.device_cert_service.resolve(
                    None, None, self.device_cert, self.device_key
                )
                or None
            )

        delay = self.reconnect_delay_seconds
        while True:
            if self.watchdog_service:
                self.watchdog_service.feed()
            try:
                self.client = MQTTClient(
                    self.client_id,
                    self.broker,
                    self.port,
                    **self._client_kwargs(),
                )
                self._apply_last_will()
                self.client.connect()
                print("Connected to MQTT Broker at", self.broker)
                return self.client
            except MQTTException as e:
                rc = self._connack_rc(e)
                if rc in PERMANENT_REJECTIONS:
                    reason = PERMANENT_REJECTIONS[rc]
                    print(
                        "MQTT connection rejected:",
                        reason,
                        "(rc=%s)" % rc,
                        "- not retrying, will report and back off",
                    )
                    raise MqttConnectionRejected(rc, reason) from e
                reason = TRANSIENT_REJECTIONS.get(rc, "unknown_rc (%s)" % rc)
                delay = self._retry_after_failure(reason, delay)
            except Exception as e:
                delay = self._retry_after_failure(e, delay)

    def _retry_after_failure(self, reason, delay):
        print("Failed to connect to MQTT broker:", reason, "- retrying in", delay, "s")
        time.sleep(delay)
        delay = min(delay * 2, self.max_reconnect_delay_seconds)
        if not self.wifi_service.is_connected():
            self.wifi_service.connect()
        return delay

    def disconnect(self):
        if self.client:
            try:
                self.client.disconnect()
                print("Disconnected from MQTT Broker")
            except Exception as e:
                print("Failed to disconnect from MQTT broker:", e)
            finally:
                self.client = None
