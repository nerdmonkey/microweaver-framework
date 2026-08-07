# Core Architecture Overview

How Microweaver's pieces fit together: the boot sequence, the service model services follow, the `BaseAdapter` contract for hardware extension points, config wiring, and WiFi/MQTT reconnect behavior. For the watchdog/boot-loop/safe-mode/reset-reason reliability story specifically, see [reliability.md](reliability.md) — this doc covers the rest of the architecture those services sit inside.

- [Boot lifecycle](#boot-lifecycle)
- [Service model](#service-model)
  - [Composition root: PublishService / SubscribeService](#composition-root-publishservice--subscribeservice)
  - [ServiceRegistry](#serviceregistry)
  - [ErrorHandlerService](#errorhandlerservice)
  - [PubSubService](#pubsubservice)
- [BaseAdapter contract](#baseadapter-contract)
- [Config](#config)
  - [Adapter-specific config](#adapter-specific-config)
- [Reconnect behavior](#reconnect-behavior)

## Boot lifecycle

```
boot.py -> _boot.run_bootstrap()
              |
              +-- gc.collect()
              +-- ResetService.read()               (logs why the last reset happened)
              +-- BootLoopGuard.check()              (increments persisted attempt counter)
              +-- import main
              +-- gc.collect()
              |
              +-- boot loop detected --> main.start_safe_mode() --> SafeModeService.run()
              |
              +-- otherwise -----------> main.start() --> PublishService.run()
```

`boot.py` (repo root) is intentionally thin — it only imports `run_bootstrap` from `_boot.py` and re-raises anything unhandled after printing it, so a crash during bootstrap is still visible on serial instead of silently rebooting:

```python
try:
    from _boot import run_bootstrap
    run_bootstrap()
except Exception as err:
    print("BOOT: unhandled exception:", err)
    raise
```

`_boot.py:run_bootstrap()` does the actual work, in a fixed order:

1. `gc.collect()` before anything else, so the reset/boot-loop checks run with a clean heap.
2. `ResetService(...).read()` — logs the previous reset's cause (`_boot.py:13`), *before* the boot-loop check, so the reason is on record even for a boot that's about to be diverted into safe mode.
3. `BootLoopGuard(...).check()` — increments the persisted attempt counter and reports whether it has exceeded `boot_loop_max_attempts` (`_boot.py:15-20`).
4. `import main` — deferred until after steps 1-3, so a bug in `main`'s own module-level code (it builds a `Setting()` at import time) can't skip reset-reason logging or the boot-loop check.
5. `gc.collect()` again, to free memory used by the import before application code runs.
6. Branch on `boot_loop_detected`: `main.start_safe_mode()` if tripped, `main.start()` otherwise (`_boot.py:26-31`).

`main.py` only defines the two entry points `_boot.py` calls — it holds no branching logic of its own:

```python
def start():
    publish = PublishService()
    publish.run()

def start_safe_mode():
    safe_mode = SafeModeService(setting.SAFE_MODE_SLEEP_SECONDS)
    safe_mode.run()
```

Once `main.start()` runs, control stays inside `PublishService.run()`'s `while True` loop for the life of the device — see [Composition root](#composition-root-publishservice--subscribeservice) and [Reconnect behavior](#reconnect-behavior) for what happens inside it.

## Service model

Every piece of hardware/network functionality in `app/services/` is a plain class: an explicit-arg constructor (no `**kwargs`), a small intention-revealing method surface over exactly one underlying concern, and failures that get printed/logged and retried rather than silently dropped. `WiFiService` (`app/services/wifi.py`) and `MqttConnection` (`app/services/mqtt.py`) are the canonical examples — see [Reconnect behavior](#reconnect-behavior).

### Composition root: PublishService / SubscribeService

`PublishService` (`app/services/publish.py`) and `SubscribeService` (`app/services/subscribe.py`) are where everything else gets wired together. Both follow the same shape: read `Setting`, conditionally construct each optional service (`WatchdogService`, `BootLoopGuard`, `MemoryMonitorService`, `HealthCheckService`, `ServiceRestartService`) only if its `_ENABLED` flag is set, then build the always-on pair `WiFiService` + `MqttConnection`.

`run()` is a two-layer loop:

```python
while True:                        # outer: reconnect after a dropped session
    self.connect_to_mqtt()
    if self.bootloop_guard:
        self.bootloop_guard.confirm()      # proves this boot reached a healthy state
    try:
        while True:                # inner: one tick per second while connected
            if self.watchdog_service:
                self.watchdog_service.feed()
            self.wifi_service.ensure_connected()
            # memory monitor / health check / service restart, if enabled
            self.publish_message(message)  # or self.client.check_msg() in SubscribeService
            time.sleep(1)
    except Exception as e:
        print("Connection lost:", e)
    finally:
        self.disconnect()
```

The only structural difference between the two: `PublishService`'s inner loop publishes on a timer, `SubscribeService`'s calls `client.check_msg()` — a non-blocking poll (`app/services/subscribe.py:112`), not `wait_msg()`. That choice matters beyond message delivery: a blocking `wait_msg()` would never return control to the loop, so nothing after it (watchdog feed, health checks) could run periodically. `check_msg()` + `sleep(1)` is what makes it possible for `SubscribeService` to feed the watchdog and poll health checks at all — keep this in mind before adding another blocking call inside either run loop.

`BootLoopGuard.confirm()` is called right after a successful MQTT connect, not after WiFi connects or the loop merely starting — connecting to the broker is the actual "healthy state" signal (see [reliability.md#boot-loop-protection](reliability.md#boot-loop-protection)).

### ServiceRegistry

`ServiceRegistry` (`app/services/registry.py`) is the boot-lifecycle contract for services that need a `start`/`stop` step beyond construction — currently just `WatchdogService.start` (`app/services/publish.py:35-36`). Services register a name plus optional `start`/`stop` callables; `start_all()` runs them in registration order, `stop_all()` runs them in reverse (last started, first stopped). A failing `start`/`stop` is logged and skipped rather than aborting the rest of boot/teardown — the same "safe to call even if setup never ran" rule `BaseAdapter.deinit()` follows.

### ErrorHandlerService

`ErrorHandlerService` (`app/services/error_handler.py`) generalizes the catch-log-continue shape that `ServiceRegistry.stop_all()`, `HealthCheckService.poll()`, and `ServiceRestartService.reconcile()` each need: `guard(fn, context)` calls `fn`, and on exception logs `unhandled_exception` at `error` level with `context` and the error string via `LogService`, returning `None` instead of propagating. `PublishService`/`SubscribeService` use it to wrap `memory_monitor_service.check` (`app/services/publish.py:108-110`) so a crash in the monitor doesn't take down the whole run loop.

### PubSubService

`PubSubService` (`app/services/pubsub.py`) is a lighter-weight publish/subscribe helper over an `MqttConnection` — `connect()`/`disconnect()`/`publish(topic, message)`/`subscribe(topic, callback)`/`check_messages()` — for callers that want direct pub/sub calls without the reliability stack (`ServiceRegistry`, watchdog, boot-loop guard, health checks) `PublishService`/`SubscribeService` wire in. It is not currently constructed anywhere in `main.py`'s boot path; treat it as a standalone building block for custom run loops, not a drop-in replacement for the composition root.

## BaseAdapter contract

`BaseAdapter` (`app/adapters/base.py`) is the frozen contract every sensor/actuator/indicator driver subclasses, extending `app/adapters/{sensors,actuators,indicators}/`. For a full walkthrough of writing, config-wiring, registering, and testing a new adapter, see [adapters.md](adapters.md).

```python
class BaseAdapter:
    _available = False

    @property
    def available(self):
        return self._available

    def setup(self):
        pass

    def deinit(self):
        pass
```

- `available` — reports whether the underlying hardware initialized successfully. Subclasses set `self._available = True` once `setup()` succeeds; nothing else should write it.
- `setup()` — lifecycle hook called once by the owning service before first use. Pin/bus configuration belongs here, not in `__init__`, so constructing an adapter stays cheap and side-effect-free (safe to instantiate during `PublishService.__init__` even if the hardware is never used).
- `deinit()` — lifecycle hook called on teardown (safe mode entry, service restart). Must be safe to call even if `setup()` never ran or already failed — mirrors the failure-tolerant contract `ServiceRegistry` and `ErrorHandlerService` also follow.

"Frozen" means: extend in subclasses (add adapter-specific methods), but don't rename or remove `available`/`setup`/`deinit` — the owning service code that drives an adapter is written against this exact surface.

## Config

`Setting` (`config/app.py`) is the single source of runtime-tunable values, backed by `device_config.json` (gitignored, real device secrets) with `device_config.json.example` as the documented template. `Setting.__init__` reads every key through `self._value(key, default)` / `self._int(key, default)` / `self._bool(key, default)` into an `UPPER_SNAKE_CASE` attribute — `_value`/`_int`/`_bool` all fall back to their `default` if the key is missing or empty, so a device with no config file at all still boots with sane defaults.

`_load()` swallows any exception opening/parsing `device_config.json` (missing file, invalid JSON) and returns `{}`, which is what makes a blank-config boot possible — the device never fails to start because of a bad or absent config file. When the file *does* parse, `_validate()` checks every present key against `_SCHEMA` (type, and where relevant `min`/`max`/`choices`) and raises `ConfigError` listing every violation at once, rather than failing on the first bad key — this only happens for keys that are present and malformed, not missing ones.

Adding a new tunable is a three-place change, and all three are required or the setting silently does nothing on-device:

1. `device_config.json.example` — snake_case key, realistic default, plus a matching entry in `_SCHEMA` if it should be validated.
2. `config/app.py` `Setting.__init__` — `UPPER_SNAKE_CASE` attribute via `self._value`/`self._int`/`self._bool`, default matching what the consuming class's own constructor would use standalone.
3. Wherever the service is constructed (`app/services/publish.py`, `app/services/subscribe.py`, or wherever else) — read `setting.YOUR_KEY` and pass it through.

### Adapter-specific config

Adapter constructors (`DHT22Adapter(pin=4)`, `RelayAdapter(pin=5)`, …) take their own sane default for pin/bus-address args, same as `WiFiService`/`MqttConnection` take theirs — an adapter must stay constructible and testable with no config file at all, which is why `tests/unit/test_dht22_adapter.py`/`test_relay_adapter.py` instantiate adapters directly without ever touching `Setting`.

`Setting` is only imported at the composition root (`main.py`), never inside an adapter module — adapters don't know `Setting` exists. `main.py` reads `setting.DHT22_PIN`/`setting.RELAY_PIN` (`config/app.py`, defaulting to `4`/`5` via `self._int(...)` — matching each adapter's own standalone default) and passes them in when building the `adapters=[(name, adapter), ...]` list handed to `PublishService`:

```python
adapters = [
    ("dht22", DHT22Adapter(pin=setting.DHT22_PIN)),
    ("relay", RelayAdapter(pin=setting.RELAY_PIN)),
]
publish = PublishService(adapters=adapters)
```

Adding a new adapter-specific setting (a pin, an I2C address, …) follows the same three-place change as any other tunable: `device_config.json.example` + `_SCHEMA` entry, `Setting.__init__` attribute, then read it at the call site that constructs the adapter — never inside the adapter class itself.

## Reconnect behavior

`WiFiService` (`app/services/wifi.py`) and `MqttConnection` (`app/services/mqtt.py`) each own one reconnect loop with the same exponential-backoff shape: start at a `reconnect_delay_seconds` delay, double it after every failed attempt, cap at `max_reconnect_delay_seconds`, retry forever (there is no max-attempts give-up — a device is expected to keep trying indefinitely until the network/broker comes back).

`WiFiService.connect()` (`app/services/wifi.py:24-44`): if already connected, returns immediately. Otherwise activates the interface, calls `wlan.connect(ssid, password)`, and waits up to `connect_timeout_seconds` (`_wait_until_connected`, polling `isconnected()` once per second) for the connection to complete. On timeout it sleeps the current backoff delay, doubles it, and retries. `ensure_connected()` is the cheap per-tick check the run loops call — it only invokes the full `connect()` retry loop if `isconnected()` is currently false.

`MqttConnection.connect()` (`app/services/mqtt.py:28-53`): ensures WiFi is connected first (calling `wifi_service.connect()` if not), then loops constructing a fresh `MQTTClient` and calling `client.connect()`. On any exception it prints the error, sleeps the current backoff delay, doubles it, and — critically — re-checks `wifi_service.is_connected()` before retrying, since a WiFi drop is a common cause of MQTT failures and there's no point hammering `MQTTClient.connect()` against a dead network link.

Both loops feed the watchdog (`watchdog_service.feed()`) on every iteration when one is configured, *inside* the retry loop rather than only in the caller's run loop — a broker or network that's slow or unreachable can otherwise starve the watchdog long enough to trigger a hardware reset mid-reconnect. See [reliability.md#hardware-watchdog](reliability.md#hardware-watchdog) for the watchdog side of this.

`PublishService`/`SubscribeService` construct one `WiFiService` and one `MqttConnection` each and call `ensure_connected()` every inner-loop tick (`app/services/publish.py:106`, `app/services/subscribe.py:101`) — reconnect is driven from inside the steady-state loop, not as a separate background task, since MicroPython on this target has no threading to run one.
