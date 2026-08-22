from app.adapters.actuators.auto_cycling_rgb import AutoCyclingRgbAdapter
from app.adapters.actuators.fan import FanAdapter
from app.adapters.actuators.relay import RelayAdapter
from app.adapters.actuators.rgb import RGBAdapter
from app.adapters.actuators.servo import ServoAdapter
from app.adapters.indicators.lcd import LCDAdapter
from app.adapters.indicators.led import StatusLEDAdapter
from app.adapters.indicators.oled import OLEDAdapter
from app.adapters.sensors.co_sensor import CoSensorAdapter
from app.adapters.sensors.dht11 import DHT11Adapter
from app.adapters.sensors.dht22 import DHT22Adapter
from app.adapters.sensors.gas_sensor import GasSensorAdapter
from app.adapters.sensors.pir import PIRAdapter
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


def _make_rgb_adapter():
    if setting.RGB_MODE == "auto_cycling":
        return AutoCyclingRgbAdapter(pin=setting.RGB_RED_PIN)
    return RGBAdapter(
        red_pin=setting.RGB_RED_PIN,
        green_pin=setting.RGB_GREEN_PIN,
        blue_pin=setting.RGB_BLUE_PIN,
    )


def _topic(base_topics, suffix):
    """Compose a device's final pub/sub topic from the configured base
    (mqtt_topic_pub/mqtt_topic_sub, first entry) plus its own topic suffix,
    e.g. base "devices/dev-42/sensors" + suffix "oled" ->
    "devices/dev-42/sensors/oled"."""
    base = base_topics[0] if base_topics else ""
    return "{}/{}".format(base, suffix) if base else suffix


def _build_publish_adapters():
    adapters = []
    topics = []
    intervals = {}
    if setting.DHT_ENABLED:
        adapters.append(("dht", _make_temperature_adapter()))
        topics.append(
            _topic(setting.MQTT_TOPIC_PUB, setting.DHT_TEMPERATURE_TOPIC_SUFFIX)
        )
        topics.append(_topic(setting.MQTT_TOPIC_PUB, setting.DHT_HUMIDITY_TOPIC_SUFFIX))
    if setting.POTENTIOMETER_ENABLED:
        name = setting.POTENTIOMETER_TOPIC_SUFFIX
        adapters.append((name, PotentiometerAdapter(pin=setting.POTENTIOMETER_PIN)))
        topics.append(_topic(setting.MQTT_TOPIC_PUB, name))
    if setting.ROTARY_ANGLE_ENABLED:
        name = setting.ROTARY_ANGLE_TOPIC_SUFFIX
        adapters.append((name, RotaryAngleAdapter(pin=setting.ROTARY_ANGLE_PIN)))
        topics.append(_topic(setting.MQTT_TOPIC_PUB, name))
    if setting.PIR_ENABLED:
        name = "pir"
        adapters.append(
            (
                name,
                PIRAdapter(
                    pin=setting.PIR_PIN, warmup_seconds=setting.PIR_WARMUP_SECONDS
                ),
            )
        )
        topics.append(_topic(setting.MQTT_TOPIC_PUB, name))
    if setting.CO_SENSOR_ENABLED:
        name = "co_sensor"
        adapters.append((name, CoSensorAdapter(pin=setting.CO_SENSOR_PIN)))
        topics.append(_topic(setting.MQTT_TOPIC_PUB, name))
        intervals[name] = setting.CO_SENSOR_HEARTBEAT_SECONDS
    if setting.GAS_SENSOR_ENABLED:
        name = "gas_sensor"
        adapters.append((name, GasSensorAdapter(pin=setting.GAS_SENSOR_PIN)))
        topics.append(_topic(setting.MQTT_TOPIC_PUB, name))
        intervals[name] = setting.GAS_SENSOR_HEARTBEAT_SECONDS
    return adapters, topics, intervals


def _build_subscribe_adapters():
    adapters = []
    topics = []
    status_topics = {}
    if setting.RELAY_ENABLED:
        name = setting.RELAY_TOPIC_SUFFIX
        adapters.append((name, RelayAdapter(pin=setting.RELAY_PIN)))
        topics.append(_topic(setting.MQTT_TOPIC_SUB, name))
        status_topics[name] = _topic(setting.MQTT_TOPIC_STATUS, name)
    if setting.RGB_ENABLED:
        name = setting.RGB_TOPIC_SUFFIX
        adapters.append((name, _make_rgb_adapter()))
        topics.append(_topic(setting.MQTT_TOPIC_SUB, name))
        status_topics[name] = _topic(setting.MQTT_TOPIC_STATUS, name)
    if setting.OLED_ENABLED:
        name = setting.OLED_TOPIC_SUFFIX
        adapters.append(
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
        topics.append(_topic(setting.MQTT_TOPIC_SUB, name))
    if setting.LCD_ENABLED:
        name = "lcd"
        adapters.append(
            (
                name,
                LCDAdapter(
                    sda_pin=setting.LCD_SDA_PIN,
                    scl_pin=setting.LCD_SCL_PIN,
                    i2c_addr=setting.LCD_I2C_ADDR,
                    rgb_addr=setting.LCD_RGB_ADDR,
                    cols=setting.LCD_COLS,
                    rows=setting.LCD_ROWS,
                    i2c_id=setting.LCD_I2C_ID,
                    default_lines=["Agnes Smart Home", setting.MQTT_USERNAME],
                ),
            )
        )
        topics.append(_topic(setting.MQTT_TOPIC_SUB, name))
        status_topics[name] = _topic(setting.MQTT_TOPIC_STATUS, name)
    if setting.SERVO_ENABLED:
        name = "servo"
        adapters.append(
            (
                name,
                ServoAdapter(
                    pin=setting.SERVO_PIN, default_angle=setting.SERVO_DEFAULT_ANGLE
                ),
            )
        )
        topics.append(_topic(setting.MQTT_TOPIC_SUB, name))
        status_topics[name] = _topic(setting.MQTT_TOPIC_STATUS, name)
    if setting.FAN_ENABLED:
        name = "fan"
        adapters.append(
            (name, FanAdapter(in1_pin=setting.FAN_IN1_PIN, in2_pin=setting.FAN_IN2_PIN))
        )
        topics.append(_topic(setting.MQTT_TOPIC_SUB, name))
        status_topics[name] = _topic(setting.MQTT_TOPIC_STATUS, name)
    if setting.OUTDOOR_LIGHT_ENABLED:
        name = "outdoor_light"
        adapters.append((name, RelayAdapter(pin=setting.OUTDOOR_LIGHT_PIN)))
        topics.append(_topic(setting.MQTT_TOPIC_SUB, name))
        status_topics[name] = _topic(setting.MQTT_TOPIC_STATUS, name)
    if setting.BUZZER_ENABLED:
        name = "buzzer"
        adapters.append((name, RelayAdapter(pin=setting.BUZZER_PIN)))
        topics.append(_topic(setting.MQTT_TOPIC_SUB, name))
        status_topics[name] = _topic(setting.MQTT_TOPIC_STATUS, name)
    return adapters, topics, status_topics


def _build_unified_publish_adapters():
    """Same enabled-adapter set as _build_publish_adapters(), without the
    per-adapter topic composition -- unified mode shares one topic for all
    of them (RuntimeService resolves it from MQTT_TOPIC_PUB directly)."""
    adapters = []
    intervals = {}
    if setting.DHT_ENABLED:
        adapters.append(("dht", _make_temperature_adapter()))
    if setting.POTENTIOMETER_ENABLED:
        name = setting.POTENTIOMETER_TOPIC_SUFFIX
        adapters.append((name, PotentiometerAdapter(pin=setting.POTENTIOMETER_PIN)))
    if setting.ROTARY_ANGLE_ENABLED:
        name = setting.ROTARY_ANGLE_TOPIC_SUFFIX
        adapters.append((name, RotaryAngleAdapter(pin=setting.ROTARY_ANGLE_PIN)))
    if setting.PIR_ENABLED:
        adapters.append(
            (
                "pir",
                PIRAdapter(
                    pin=setting.PIR_PIN, warmup_seconds=setting.PIR_WARMUP_SECONDS
                ),
            )
        )
    if setting.CO_SENSOR_ENABLED:
        adapters.append(("co_sensor", CoSensorAdapter(pin=setting.CO_SENSOR_PIN)))
        intervals["co_sensor"] = setting.CO_SENSOR_HEARTBEAT_SECONDS
    if setting.GAS_SENSOR_ENABLED:
        adapters.append(("gas_sensor", GasSensorAdapter(pin=setting.GAS_SENSOR_PIN)))
        intervals["gas_sensor"] = setting.GAS_SENSOR_HEARTBEAT_SECONDS
    return adapters, intervals


def _build_unified_subscribe_adapters():
    """Same enabled-adapter set as _build_subscribe_adapters(), without the
    per-adapter topic/status-topic composition -- unified mode shares one
    command topic (dispatched by JSON key) and one state topic for all of
    them."""
    adapters = []
    if setting.RELAY_ENABLED:
        name = setting.RELAY_TOPIC_SUFFIX
        adapters.append((name, RelayAdapter(pin=setting.RELAY_PIN)))
    if setting.RGB_ENABLED:
        name = setting.RGB_TOPIC_SUFFIX
        adapters.append((name, _make_rgb_adapter()))
    if setting.OLED_ENABLED:
        name = setting.OLED_TOPIC_SUFFIX
        adapters.append(
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
    if setting.LCD_ENABLED:
        adapters.append(
            (
                "lcd",
                LCDAdapter(
                    sda_pin=setting.LCD_SDA_PIN,
                    scl_pin=setting.LCD_SCL_PIN,
                    i2c_addr=setting.LCD_I2C_ADDR,
                    rgb_addr=setting.LCD_RGB_ADDR,
                    cols=setting.LCD_COLS,
                    rows=setting.LCD_ROWS,
                    i2c_id=setting.LCD_I2C_ID,
                    default_lines=["Agnes Smart Home", setting.MQTT_USERNAME],
                ),
            )
        )
    if setting.SERVO_ENABLED:
        adapters.append(
            (
                "servo",
                ServoAdapter(
                    pin=setting.SERVO_PIN, default_angle=setting.SERVO_DEFAULT_ANGLE
                ),
            )
        )
    if setting.FAN_ENABLED:
        adapters.append(
            ("fan", FanAdapter(in1_pin=setting.FAN_IN1_PIN, in2_pin=setting.FAN_IN2_PIN))
        )
    if setting.OUTDOOR_LIGHT_ENABLED:
        adapters.append(("outdoor_light", RelayAdapter(pin=setting.OUTDOOR_LIGHT_PIN)))
    if setting.BUZZER_ENABLED:
        adapters.append(("buzzer", RelayAdapter(pin=setting.BUZZER_PIN)))
    return adapters


def start():
    if setting.UNIFIED_MQTT_CONTRACT_ENABLED:
        publish_adapters, publish_intervals = _build_unified_publish_adapters()
        subscribe_adapters = _build_unified_subscribe_adapters()
        runtime = RuntimeService(
            publish_adapters=publish_adapters,
            subscribe_adapters=subscribe_adapters,
            publish_intervals=publish_intervals,
            unified_mode=True,
        )
        runtime.run()
        return

    publish_adapters, publish_topics, publish_intervals = _build_publish_adapters()
    subscribe_adapters, subscribe_topics, status_topics = _build_subscribe_adapters()
    topics = subscribe_topics if subscribe_adapters else []
    runtime = RuntimeService(
        publish_adapters=publish_adapters,
        subscribe_adapters=subscribe_adapters,
        topics=topics,
        topics_pub=publish_topics,
        topics_status=status_topics,
        publish_intervals=publish_intervals,
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
