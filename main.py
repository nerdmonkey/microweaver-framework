from app.adapters.actuators.relay import RelayAdapter
from app.adapters.indicators.led import StatusLEDAdapter
from app.adapters.sensors.dht11 import DHT11Adapter
from app.adapters.sensors.dht22 import DHT22Adapter
from app.services.provisioning import ProvisioningService
from app.services.registration import RegistrationService
from app.services.runtime import RuntimeService
from app.services.safe_mode import SafeModeService
from app.services.wifi import WiFiService
from config.app import Setting

setting = (Setting()).get_settings()


def _make_temperature_adapter():
    adapter_cls = DHT22Adapter
    adapter_name = "dht22"
    if setting.DHT_SENSOR_TYPE == "dht11":
        adapter_cls = DHT11Adapter
        adapter_name = "dht11"
    return adapter_name, adapter_cls(pin=setting.DHT_PIN)


def start():
    publish_adapters = []
    if setting.DHT_ENABLED:
        publish_adapters.append(_make_temperature_adapter())
    if setting.POTENTIOMETER_ENABLED:
        from app.adapters.sensors.potentiometer import PotentiometerAdapter

        publish_adapters.append(
            ("potentiometer", PotentiometerAdapter(pin=setting.POTENTIOMETER_PIN))
        )
    if setting.ROTARY_ANGLE_ENABLED:
        from app.adapters.sensors.rotary_angle import RotaryAngleAdapter

        publish_adapters.append(
            ("rotary_angle", RotaryAngleAdapter(pin=setting.ROTARY_ANGLE_PIN))
        )
    subscribe_adapters = []
    if setting.RELAY_ENABLED:
        subscribe_adapters.append(("relay", RelayAdapter(pin=setting.RELAY_PIN)))
    if setting.OLED_ENABLED:
        # Deferred import: app.libs.ssd1306 is a sizeable framebuf-based
        # driver, and loading it adds heap pressure that can starve the
        # ESP32 WiFi driver's rx-buffer allocation on boot (see the
        # "WiFi Out of Memory" crash in RuntimeService's WiFiService
        # construction, only reproducible on-device). Import it only when
        # the display is actually wired up.
        from app.adapters.indicators.oled import OLEDAdapter

        subscribe_adapters.append(
            (
                "oled",
                OLEDAdapter(
                    sda_pin=setting.OLED_SDA_PIN,
                    scl_pin=setting.OLED_SCL_PIN,
                    i2c_addr=setting.OLED_I2C_ADDR,
                    width=setting.OLED_WIDTH,
                    height=setting.OLED_HEIGHT,
                ),
            )
        )
    topics = None if subscribe_adapters else []
    runtime = RuntimeService(
        publish_adapters=publish_adapters,
        subscribe_adapters=subscribe_adapters,
        topics=topics,
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
