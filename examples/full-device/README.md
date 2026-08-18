# Full device example

A copy-and-adapt reference showing every stage of a real Microweaver device
wired together: first-boot provisioning, WiFi/MQTT connect, a sensor +
actuator + indicator adapter, OTA updates, and observability (logging,
metrics, health checks, crash log). Nothing here is new framework code --
it's [`main.py`](../../main.py) with a `StatusLEDAdapter` added as a second
subscribe adapter, so you can see all three adapter kinds wired through
[`RuntimeService`](../../app/services/runtime.py) at once.

## What runs, and where

The boot-time decision tree ([`_boot.py`](../../_boot.py), unchanged by this
example) picks one of these entry points depending on device state:

```
_boot.run_bootstrap()
    |
    +-- no WIFI_SSID configured   --> main.start_provisioning()
    +-- boot-loop detected        --> main.start_safe_mode()
    +-- claim pending             --> main.start_claim()
    +-- otherwise                 --> main.start()   <-- this example's focus
```

Provisioning, safe mode, and claim registration are already fully described
in [docs/provisioning.md](../../docs/provisioning.md) -- `start_provisioning()`
and `start_claim()` in this example's `main.py` are verbatim copies of the
root ones, included only so the file is a complete drop-in replacement.

## `start()`: adapters -> RuntimeService -> OTA + observability

```python
sensor_name, sensor_adapter = _make_temperature_adapter()          # sensor
runtime = RuntimeService(
    publish_adapters=[(sensor_name, sensor_adapter)],
    subscribe_adapters=[
        ("relay", RelayAdapter(pin=setting.RELAY_PIN)),             # actuator
        ("led", StatusLEDAdapter(pin=STATUS_LED_PIN)),               # indicator
    ],
)
runtime.run()
```

- **Sensor** (`DHT22Adapter`/`DHT11Adapter`) is a *publish* adapter:
  `RuntimeService` polls `.read()` on a `PollScheduler` tick and publishes the
  reading to `mqtt_topic_pub`.
- **Actuator** (`RelayAdapter`) and **indicator** (`StatusLEDAdapter`) are
  both *subscribe* adapters. `RuntimeService` doesn't distinguish between
  "actuator" and "indicator" as types -- anything with `on()`/`off()`/
  `toggle()` can be driven by an MQTT command, which is why an LED plugs in
  with zero extra code. Point `mqtt_topic_sub` at one command topic per
  adapter name so commands route correctly:

  ```json
  "mqtt_topic_sub": ["command/control/room/relay", "command/control/room/led"]
  ```

  A topic ending in `relay` drives the relay; a topic ending in `led` drives
  the LED. See [docs/adapters.md](../../docs/adapters.md) for how command
  routing and payload decoding (`"on"`, `"off"`, `"toggle"`, or `{"state":
  "on"}`) work.
- **OTA** and **observability** (structured logging, metrics, health checks,
  crash log capture, memory monitor, watchdog) are not wired in `start()` at
  all -- `RuntimeService.__init__` builds all of them itself, each gated by
  its own `device_config.json` flag. This example only has to hand
  `RuntimeService` its adapters; see [docs/ota.md](../../docs/ota.md) and
  [docs/observability.md](../../docs/observability.md) for what each flag
  enables and how to read the resulting health/metrics payloads.

## Using this example

1. Copy `examples/full-device/main.py` over your project's `main.py`.
2. Adjust `STATUS_LED_PIN` (and `RELAY_PIN`/`DHT_PIN` via
   `device_config.json`) to match your wiring.
3. Enable the pieces you want in `device_config.json` (copy
   `device_config.json.example` if you haven't already) -- `ota_enabled`,
   `health_check_enabled`, `watchdog_enabled`, `memory_monitor_enabled`,
   `claim_enabled`, etc. Everything defaults off except MQTT/autostart, so
   you can turn features on incrementally.
4. Deploy as usual (`python tinker.py deploy`, see the root
   [README](../../README.md#building-and-deploying)) -- `boot.py`/`_boot.py`
   don't need to change for anything in this example.
