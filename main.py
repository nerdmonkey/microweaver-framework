from app.adapters.actuators.relay import RelayAdapter
from app.adapters.actuators.rgb import RGBAdapter
from app.adapters.indicators.led import StatusLEDAdapter
from app.adapters.indicators.oled import OLEDAdapter
from app.adapters.sensors.dht11 import DHT11Adapter
from app.adapters.sensors.dht22 import DHT22Adapter
from app.adapters.sensors.potentiometer import PotentiometerAdapter
from app.adapters.sensors.rotary_angle import RotaryAngleAdapter
from app.services.provisioning import ProvisioningService
from app.services.registration import RegistrationService
from app.services.runtime import RuntimeService
from app.services.safe_mode import SafeModeService
from app.services.wifi import WiFiService
from config.app import Setting

setting = (Setting()).get_settings()


def _make_temperature_adapter():
    adapter_cls = DHT22Adapter
    if setting.DHT_SENSOR_TYPE == "dht11":
        adapter_cls = DHT11Adapter
    return adapter_cls(pin=setting.DHT_PIN)


def start():
    # Adapter names double as the JSON keys RuntimeService uses in the unified
    # devices/{mqtt_username}/{data,command,state} envelope -- RuntimeService
    # derives the actual topics itself, no per-adapter topic composition here.
    publish_adapters = []
    if setting.DHT_ENABLED:
        publish_adapters.append(("dht", _make_temperature_adapter()))
    if setting.POTENTIOMETER_ENABLED:
        name = setting.POTENTIOMETER_TOPIC_SUFFIX
        publish_adapters.append(
            (name, PotentiometerAdapter(pin=setting.POTENTIOMETER_PIN))
        )
    if setting.ROTARY_ANGLE_ENABLED:
        name = setting.ROTARY_ANGLE_TOPIC_SUFFIX
        publish_adapters.append(
            (name, RotaryAngleAdapter(pin=setting.ROTARY_ANGLE_PIN))
        )
    subscribe_adapters = []
    if setting.RELAY_ENABLED:
        name = setting.RELAY_TOPIC_SUFFIX
        subscribe_adapters.append((name, RelayAdapter(pin=setting.RELAY_PIN)))
    if setting.RGB_ENABLED:
        name = setting.RGB_TOPIC_SUFFIX
        subscribe_adapters.append(
            (
                name,
                RGBAdapter(
                    red_pin=setting.RGB_RED_PIN,
                    green_pin=setting.RGB_GREEN_PIN,
                    blue_pin=setting.RGB_BLUE_PIN,
                ),
            )
        )
    if setting.OLED_ENABLED:
        name = setting.OLED_TOPIC_SUFFIX
        subscribe_adapters.append(
            (
                name,
                OLEDAdapter(
                    sda_pin=setting.OLED_SDA_PIN,
                    scl_pin=setting.OLED_SCL_PIN,
                    i2c_addr=setting.OLED_I2C_ADDR,
                    width=setting.OLED_WIDTH,
                    height=setting.OLED_HEIGHT,
                ),
            )
        )
    runtime = RuntimeService(
        publish_adapters=publish_adapters,
        subscribe_adapters=subscribe_adapters,
    )
    runtime.run()


def start_safe_mode():
    safe_mode = SafeModeService(setting.SAFE_MODE_SLEEP_SECONDS)
    safe_mode.run()


def start_provisioning():
    led = None
    if setting.PROVISIONING_LED_ENABLED:
        led = StatusLEDAdapter(pin=setting.PROVISIONING_LED_PIN)
        led.setup()
    provisioning = ProvisioningService(
        ap_ssid=setting.PROVISIONING_AP_SSID,
        ap_password=setting.PROVISIONING_AP_PASSWORD,
        ap_ip=setting.PROVISIONING_AP_IP,
        port=setting.PROVISIONING_PORT,
        setting=setting,
        led=led,
    )
    try:
        provisioning.run()
    finally:
        if led:
            led.deinit()


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
