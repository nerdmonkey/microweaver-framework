from app.adapters.actuators.relay import RelayAdapter
from app.adapters.sensors.dht22 import DHT22Adapter
from app.services.provisioning import ProvisioningService
from app.services.publish import PublishService
from app.services.safe_mode import SafeModeService
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


if __name__ == "__main__":
    start()
