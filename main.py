from app.adapters.actuators.relay import RelayAdapter
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
    return setting.DHT_TOPIC_SUFFIX, adapter_cls(pin=setting.DHT_PIN)


def _topic(base_topics, suffix):
    """Compose a device's final pub/sub topic from the configured base
    (mqtt_topic_pub/mqtt_topic_sub, first entry) plus its own topic suffix,
    e.g. base "data/sensor/room" + suffix "oled" -> "data/sensor/room/oled"."""
    base = base_topics[0] if base_topics else ""
    return "{}/{}".format(base, suffix) if base else suffix


def start():
    publish_adapters = []
    publish_topics = []
    if setting.DHT_ENABLED:
        name, adapter = _make_temperature_adapter()
        publish_adapters.append((name, adapter))
        publish_topics.append(_topic(setting.MQTT_TOPIC_PUB, name))
    if setting.POTENTIOMETER_ENABLED:
        name = setting.POTENTIOMETER_TOPIC_SUFFIX
        publish_adapters.append(
            (name, PotentiometerAdapter(pin=setting.POTENTIOMETER_PIN))
        )
        publish_topics.append(_topic(setting.MQTT_TOPIC_PUB, name))
    if setting.ROTARY_ANGLE_ENABLED:
        name = setting.ROTARY_ANGLE_TOPIC_SUFFIX
        publish_adapters.append(
            (name, RotaryAngleAdapter(pin=setting.ROTARY_ANGLE_PIN))
        )
        publish_topics.append(_topic(setting.MQTT_TOPIC_PUB, name))
    subscribe_adapters = []
    subscribe_topics = []
    if setting.RELAY_ENABLED:
        name = setting.RELAY_TOPIC_SUFFIX
        subscribe_adapters.append((name, RelayAdapter(pin=setting.RELAY_PIN)))
        subscribe_topics.append(_topic(setting.MQTT_TOPIC_SUB, name))
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
        subscribe_topics.append(_topic(setting.MQTT_TOPIC_SUB, name))
    topics = subscribe_topics if subscribe_adapters else []
    runtime = RuntimeService(
        publish_adapters=publish_adapters,
        subscribe_adapters=subscribe_adapters,
        topics=topics,
        topics_pub=publish_topics,
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
