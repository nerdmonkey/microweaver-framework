from app.adapters.actuators.relay import RelayAdapter
from app.adapters.sensors.dht22 import DHT22Adapter
from app.services.provisioning import ProvisioningService
from app.services.publish import PublishService
from app.services.registration import RegistrationService
from app.services.safe_mode import SafeModeService
from app.services.wifi import WiFiService
from config.app import Setting

setting = (Setting()).get_settings()


def start():
    adapters = [
        ("dht22", DHT22Adapter(pin=setting.DHT22_PIN)),
        ("relay", RelayAdapter(pin=setting.RELAY_PIN)),
    ]
    publish = PublishService(adapters=adapters)
    publish.run()


def start_safe_mode():
    safe_mode = SafeModeService(setting.SAFE_MODE_SLEEP_SECONDS)
    safe_mode.run()


def start_provisioning():
    provisioning = ProvisioningService(
        ap_ssid=setting.PROVISIONING_AP_SSID,
        ap_password=setting.PROVISIONING_AP_PASSWORD,
        ap_ip=setting.PROVISIONING_AP_IP,
        port=setting.PROVISIONING_PORT,
        setting=setting,
    )
    provisioning.run()


def start_claim():
    wifi = WiFiService(
        ssid=setting.WIFI_SSID,
        password=setting.WIFI_PASSWORD,
        connect_timeout_seconds=setting.WIFI_CONNECT_TIMEOUT_SECONDS,
        reconnect_delay_seconds=setting.WIFI_RECONNECT_DELAY_SECONDS,
        max_reconnect_delay_seconds=setting.WIFI_MAX_RECONNECT_DELAY_SECONDS,
        disable_power_save=setting.WIFI_DISABLE_POWER_SAVE,
    )
    wifi.connect()
    registration = RegistrationService(
        claim_url=setting.CLAIM_URL,
        claim_code=setting.CLAIM_CODE,
        setting=setting,
    )
    registration.register()


if __name__ == "__main__":
    start()
