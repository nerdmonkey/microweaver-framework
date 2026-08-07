import time

import machine

from app.services.mqtt import MqttConnection
from app.services.ota import OtaService
from app.services.wifi import WiFiService
from config.app import Setting

setting = (Setting()).get_settings()


class SafeModeService:
    def __init__(self, sleep_seconds=5):
        self.sleep_seconds = sleep_seconds
        self.ota_topic = setting.OTA_TOPIC
        self.wifi_service = None
        self.connection = None
        self.ota_service = None
        self.client = None
        if setting.WIFI_SSID and setting.MQTT_ENABLED and setting.OTA_ENABLED:
            self.wifi_service = WiFiService(
                setting.WIFI_SSID,
                setting.WIFI_PASSWORD,
                setting.WIFI_CONNECT_TIMEOUT_SECONDS,
                setting.WIFI_RECONNECT_DELAY_SECONDS,
                setting.WIFI_MAX_RECONNECT_DELAY_SECONDS,
            )
            self.connection = MqttConnection(
                setting.MQTT_CLIENT_ID,
                setting.MQTT_BROKER,
                setting.MQTT_PORT,
                self.wifi_service,
                setting.MQTT_RECONNECT_DELAY_SECONDS,
                setting.MQTT_MAX_RECONNECT_DELAY_SECONDS,
                setting.MQTT_KEEPALIVE_SECONDS,
                username=setting.MQTT_USERNAME,
                password=setting.MQTT_PASSWORD,
            )
            self.ota_service = OtaService(
                setting.OTA_MANIFEST_URL,
                setting=setting,
                state_path=setting.OTA_STATE_PATH,
            )

    def run(self):
        print("SAFE MODE: user services disabled, awaiting recovery/reflash")
        if self._recovery_enabled():
            self._run_recovery_loop()
        else:
            self._sleep_forever()

    def _recovery_enabled(self):
        return self.wifi_service is not None

    def _run_recovery_loop(self):
        while True:
            self.client = self.connection.connect()
            self.client.set_callback(self._on_message)
            self.client.subscribe(self.ota_topic)
            print("SAFE MODE: listening for OTA update on", self.ota_topic)
            try:
                while True:
                    self.client.check_msg()
                    time.sleep(self.sleep_seconds)
            except Exception as e:
                print("SAFE MODE: recovery listener lost connection:", e)
            finally:
                self.connection.disconnect()

    def _on_message(self, topic, message):
        print("SAFE MODE: OTA update triggered:", message.decode())
        try:
            if self.ota_service.apply_update():
                print("SAFE MODE: update applied, restarting")
                machine.reset()
        except Exception as e:
            print("SAFE MODE: OTA update failed:", e)

    def _sleep_forever(self):
        while True:
            time.sleep(self.sleep_seconds)
