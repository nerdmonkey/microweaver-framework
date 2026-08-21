# MQTT Contract (Unified, RuntimeService)

Firmware-side implementation notes for the unified MQTT contract. **The canonical protocol contract — topic names, payload shapes, component value types/ranges — lives in `agnes-smart-home/CLAUDE.md` under "MQTT & Component Value Contract".** This doc explains how `RuntimeService` (`app/services/runtime.py`) implements that contract; if the two ever disagree, the CLAUDE.md table wins and this doc is out of date.

- [Scope](#scope)
- [The four topics](#the-four-topics)
- [Telemetry: merged publish](#telemetry-merged-publish)
- [Command: JSON-key routing](#command-json-key-routing)
- [State: the `state()` adapter method](#state-the-state-adapter-method)
- [Availability: birth + LWT](#availability-birth--lwt)
- [Adding a new component to the contract](#adding-a-new-component-to-the-contract)
- [What this doc does NOT cover](#what-this-doc-does-not-cover)

## Scope

Applies to devices whose backend `Device.firmware_version` clears the unified-contract threshold (`0.3.0`, see `speaks_unified_mqtt_contract()` in `agnes-smart-home/agnes-iot-platform/api/app/services/component_topic_service.py`). Below that version, or if the version is unset, the backend falls back to legacy per-component-type topics — a device stays on whichever pattern its reported version selects; there is no runtime negotiation.

## The four topics

All derived in `RuntimeService.__init__` from `setting.MQTT_USERNAME` (the device's MQTT username, same value as the backend's `credential.username`):

```python
self.topic_data = "devices/{}/data".format(setting.MQTT_USERNAME)
self.topic_command = "devices/{}/command".format(setting.MQTT_USERNAME)
self.topic_state = "devices/{}/state".format(setting.MQTT_USERNAME)
self.topic_availability = "devices/{}/availability".format(setting.MQTT_USERNAME)
```

`topics_pub`/`topics`/`topics_status` constructor args still exist for explicit override (used by `examples/full-device/main.py` in some configurations), but `main.py`'s real wiring no longer passes them — the four topics above are the default.

## Telemetry: merged publish

`_poll_publish_adapters()` collects every enabled publish adapter's latest reading into one dict per tick, keyed by adapter name (the same name passed into `RuntimeService(publish_adapters=[(name, adapter), ...])`), and publishes it once to `topic_data`. DHT's dual `(temperature, humidity)` reading contributes two keys — `DHT_TEMPERATURE_TOPIC_SUFFIX`/`DHT_HUMIDITY_TOPIC_SUFFIX` config values, repurposed as JSON key names rather than topic suffixes.

Change-only adapters (`PotentiometerAdapter`, `RotaryAngleAdapter`) are still suppressed from the merge when the reading hasn't moved past `CHANGE_THRESHOLD_PERCENT`.

## Command: JSON-key routing

`_handle_command_message()` parses the payload as JSON. If it's a dict, each key is looked up against `subscribe_adapter_map` (built from `RuntimeService(subscribe_adapters=[(name, adapter), ...])`); `request_id` is always skipped. A device with exactly one subscribe adapter also accepts a bare non-JSON command, or a JSON dict whose keys don't match any adapter name (e.g. legacy `{"state": "toggle"}`) — both fall back to that one adapter, so single-adapter setups don't need to know their own adapter name.

Each matched value goes through `_apply_command(adapter, value)`:
- `{"command": "<method>", ...params}` → `_apply_structured_command`: `getattr(adapter, method)(**params)`. Refuses private methods (leading `_`) and `setup`/`deinit`.
- Anything else → `_decode_command_value` normalizes to `"on"`/`"off"`/`"toggle"` and calls the matching method directly.

This is why adding parameterized control to an adapter (see `RGBAdapter.set(color=None, brightness=None)`) needs no runtime.py change — the dispatcher calls whatever public method the payload names.

## State: the `state()` adapter method

After any command that changed something, and periodically (`state_report_interval_seconds`, default 60s, via `state_report_scheduler`), `_publish_state()` builds one merged dict across all subscribe adapters and publishes it to `topic_state`:

```python
for name, adapter in self.subscribe_adapters:
    if hasattr(adapter, "state"):
        state[name] = adapter.state()
    elif hasattr(adapter, "is_on"):
        state[name] = "on" if adapter.is_on() else "off"
```

An adapter with no meaningful state beyond binary (`RelayAdapter`) doesn't need a `state()` method — `is_on()` is the fallback. An adapter with real parameters (`RGBAdapter`, `StatusLEDAdapter`) should implement `state()` returning either the bare string `"off"` or a dict of its actual current parameters — see `RGBAdapter.state()` for the pattern (reports the *requested* base color/brightness, not the brightness-scaled PWM duty values actually written to the pins).

## Availability: birth + LWT

`connect_to_mqtt()` publishes `{"state": "online"}` (retained, always — regardless of `MQTT_PUBLISH_RETAIN`) to `topic_availability` immediately after a successful connect. The LWT (offline) side is configured separately via `mqtt_lwt_topic`/`mqtt_lwt_message` in `device_config.json`, applied by `MqttConnection._apply_last_will()` (`app/services/mqtt.py`) before `connect()` — both should point at the same `.../availability` topic with `{"state":"offline"}`.

## Adding a new component to the contract

1. Add the adapter (`docs/adapters.md` — subclass `BaseAdapter`, implement whatever methods the component needs).
2. Wire it into `main.py`'s `start()` as a `publish_adapters`/`subscribe_adapters` entry, name = the JSON key it'll appear under.
3. If it has real state beyond on/off, add `state()`.
4. If it needs parameterized commands, expose a public method for the dispatcher to call by name (e.g. `set(...)`) — no `runtime.py` change needed.
5. Add its row to the canonical table in `agnes-smart-home/CLAUDE.md` — value type, range/unit, valid commands. Do this when the adapter ships, not before.

## What this doc does NOT cover

- The legacy per-component-type topic pattern (`devices/{username}/commands/relay`, `.../relay/status`, etc.) used by devices below the firmware-version threshold — that's still live backend-side (`component_topic_service.py`'s non-unified branch) but isn't part of this contract.
- `devices/esp32-starter-kit`/`devices/pico-starter-kit` (separate firmware in `agnes-smart-home/devices/`, not this repo) — different topic conventions, not covered here.
- `architecture.md`'s "Composition root: PublishService / SubscribeService" section describes the pre-`RuntimeService` design and is stale with respect to this contract; `RuntimeService` is the actual composition root today.
