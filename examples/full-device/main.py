"""
Full device reference example.

Shows every stage wired together: provisioning -> WiFi/MQTT connect ->
adapters (sensor + actuator + indicator) -> OTA -> observability. Copy this
file over your project's `main.py`. `boot.py` and `_boot.py` are unchanged --
copy them as-is from the repo root; they already drive the provisioning /
claim / safe-mode decision tree this example's `start()` is the endpoint of.

See examples/full-device/README.md for the end-to-end walkthrough and links
to the docs each stage comes from.
"""

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

# Runtime status LED pin. Separate from `provisioning_led_pin`
# (docs/provisioning.md) -- that one signals AP-mode state during setup, this
# one is a normal command-driven indicator during regular operation.
STATUS_LED_PIN = 15


def _make_temperature_adapter():
    adapter_cls = DHT22Adapter
    adapter_name = "dht22"
    if setting.DHT_SENSOR_TYPE == "dht11":
        adapter_cls = DHT11Adapter
        adapter_name = "dht11"
    return adapter_name, adapter_cls(pin=setting.DHT_PIN)


def start():
    # --- Adapters: sensor (publish), actuator + indicator (subscribe) ---
    # RuntimeService drives any subscribe adapter that exposes on()/off()/
    # toggle() from MQTT commands, so a StatusLEDAdapter plugs in as a
    # remotely-triggerable indicator the same way RelayAdapter plugs in as
    # an actuator -- no indicator-specific glue code needed. Point
    # mqtt_topic_sub at one topic per adapter name, e.g.
    # ["command/control/room/relay", "command/control/room/led"]; a command
    # topic that ends in "relay" or "led" is routed to that adapter.
    sensor_name, sensor_adapter = _make_temperature_adapter()
    runtime = RuntimeService(
        publish_adapters=[(sensor_name, sensor_adapter)],
        subscribe_adapters=[
            ("relay", RelayAdapter(pin=setting.RELAY_PIN)),
            ("led", StatusLEDAdapter(pin=STATUS_LED_PIN)),
        ],
    )

    # --- OTA + observability ---
    # Not wired here: RuntimeService.__init__ (app/services/runtime.py)
    # already builds logging, metrics, health checks, crash log, memory
    # monitor, watchdog and OTA itself, each gated by its own
    # device_config.json flag (ota_enabled, health_check_enabled,
    # memory_monitor_enabled, watchdog_enabled, ...). This example only
    # hands RuntimeService its adapters; see docs/ota.md and
    # docs/observability.md for what each flag turns on and how to read the
    # health/metrics output.
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
