# Writing a New Adapter

How to add a new sensor, actuator, or indicator driver to Microweaver: subclassing `BaseAdapter`, where `setup()`/`deinit()` logic belongs, wiring config through `Setting`, registering lifecycle with `ServiceRegistry`, scheduling periodic reads with `PollScheduler`, and testing against `conftest.py`'s MicroPython stubs. For the frozen contract itself and how adapters fit the rest of the runtime, see [architecture.md#baseadapter-contract](architecture.md#baseadapter-contract).

- [Before you start](#before-you-start)
- [The BaseAdapter contract](#the-baseadapter-contract)
- [Step 1: Choose a location and subclass](#step-1-choose-a-location-and-subclass)
- [Step 2: Constructor — explicit args, no side effects](#step-2-constructor--explicit-args-no-side-effects)
- [Step 3: `setup()` — hardware init lives here](#step-3-setup--hardware-init-lives-here)
- [Step 4: Adapter-specific methods](#step-4-adapter-specific-methods)
- [Step 5: `deinit()` — safe to call from any state](#step-5-deinit--safe-to-call-from-any-state)
- [Wiring config through Setting](#wiring-config-through-setting)
- [Registering lifecycle with ServiceRegistry](#registering-lifecycle-with-serviceregistry)
- [Scheduling periodic reads with PollScheduler](#scheduling-periodic-reads-with-pollscheduler)
- [Bench-testing on real hardware](#bench-testing-on-real-hardware)
- [Testing against conftest.py's stubs](#testing-against-conftestpys-stubs)
- [Worked example: RelayAdapter](#worked-example-relayadapter)
- [Checklist](#checklist)

## Before you start

Read [architecture.md#baseadapter-contract](architecture.md#baseadapter-contract) first — this doc assumes you already know what "frozen" means there (extend, never rename/remove `available`/`setup`/`deinit`). Three working reference implementations exist and are the best models to copy from directly:

| Kind | File | Test file |
|---|---|---|
| Sensor | `app/adapters/sensors/dht22.py` | `tests/unit/test_dht22_adapter.py` |
| Actuator | `app/adapters/actuators/relay.py` | `tests/unit/test_relay_adapter.py` |
| Indicator | `app/adapters/indicators/led.py` | `tests/unit/test_led_adapter.py` |

## The BaseAdapter contract

`app/adapters/base.py`, in full:

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

Three things every adapter subclass owns:

- `available` — read-only property. Subclasses set `self._available = True`/`False`, nothing external writes it.
- `setup()` — called once by whatever constructs the adapter, before first use.
- `deinit()` — called on teardown (safe mode entry, service restart). Must not assume `setup()` ran or succeeded.

---

## Step 1: Choose a location and subclass

Sensors go in `app/adapters/sensors/`, actuators in `app/adapters/actuators/`, indicators (LEDs, buzzers, displays) in `app/adapters/indicators/`. One adapter per file, file name matching the hardware (`dht22.py`, `relay.py`, `led.py`).

```python
from app.adapters.base import BaseAdapter


class MyAdapter(BaseAdapter):
    ...
```

## Step 2: Constructor — explicit args, no side effects

Named args with sane defaults, same rule as `app/services/`. No `**kwargs`. The constructor only assigns instance attributes — no hardware access, no imports of `machine`/`dht`/etc. executed yet, so instantiating the adapter is always cheap and safe even if the hardware is never used:

```python
def __init__(self, pin=5, active_high=True):
    self.pin = pin
    self.active_high = active_high
    self._relay = None
    self._on = False
```

## Step 3: `setup()` — hardware init lives here

All actual hardware access (`machine.Pin(...)`, `machine.PWM(...)`, `dht.DHT22(...)`, bus/pin configuration) happens in `setup()`, wrapped in `try`/`except`. On success set `self._available = True`; on failure, print the error, reset the handle to `None`, and set `self._available = False`. Never raise out of `setup()` — a failed adapter must leave the device bootable, not crash it:

```python
def setup(self):
    try:
        self._relay = machine.Pin(self.pin, machine.Pin.OUT)
        self._available = True
        self.off()
    except Exception as e:
        print("Failed to setup relay:", e)
        self._relay = None
        self._available = False
```

## Step 4: Adapter-specific methods

Everything beyond `available`/`setup`/`deinit` is yours to add — `read()`/`temperature()`/`humidity()` for a sensor, `on()`/`off()`/`toggle()`/`is_on()` for an actuator, `set_brightness()`/`brightness()` for an indicator. Guard every method on `self._available` and no-op (or return `None`) when the adapter isn't available, rather than letting it raise on a `None` handle:

```python
def on(self):
    if not self._available:
        return
    self._relay.value(1 if self.active_high else 0)
    self._on = True
```

## Step 5: `deinit()` — safe to call from any state

Unconditionally reset internal handles and flags to their construction-time defaults. If the handle needs its own teardown call (e.g. `machine.PWM.deinit()`, as `StatusLEDAdapter` does), wrap only that call in `try`/`except` so a failing hardware teardown still lets the rest of `deinit()` run. Must succeed whether `setup()` never ran, failed, or succeeded:

```python
def deinit(self):
    self._relay = None
    self._available = False
    self._on = False
```

---

## Wiring config through Setting

If the adapter needs a device-specific value (a pin number, an active-high flag), don't hardcode it at the call site — read it from `Setting` the same three-place way every other tunable is added, and the same way `main.py` already does for `DHT22Adapter`/`RelayAdapter` (full pattern: [architecture.md#adapter-specific-config](architecture.md#adapter-specific-config)):

1. `device_config.json.example` — add the snake_case key with a realistic default plus a `_SCHEMA` entry, e.g. `"relay_pin": 5`.
2. `config/app.py` `Setting.__init__` — add the `UPPER_SNAKE_CASE` attribute:
   ```python
   self.RELAY_PIN = self._int("relay_pin", 5)
   ```
3. `main.py` (or wherever the composition happens) — read it and pass it in when constructing the adapter:
   ```python
   RelayAdapter(pin=setting.RELAY_PIN)
   ```

The adapter's own constructor default (Step 2 above) should match the `Setting` default, so the adapter behaves the same whether it's constructed directly (e.g. in a test) or via `Setting`. Note `Setting` is only ever imported at the composition root (`main.py`) — never inside an adapter module itself, so adapters stay constructible and testable with no config file at all.

## Registering lifecycle with ServiceRegistry

`PublishService`/`SubscribeService` (`app/services/publish.py`, `app/services/subscribe.py`) both take an optional `adapters` constructor arg: a list of `(name, adapter)` pairs.

```python
relay = RelayAdapter(pin=setting.RELAY_PIN)
led = StatusLEDAdapter()

publish = PublishService(adapters=[("relay", relay), ("led", led)])
```

Internally, `_register_adapters()` hands each pair to `self.registry.register_adapter(name, adapter)` (`app/services/registry.py`), which bridges the adapter's `setup`/`deinit` onto the registry's `start`/`stop` slots:

```python
def register_adapter(self, name, adapter):
    return self.register(name, start=adapter.setup, stop=adapter.deinit)
```

`registry.start_all()` — called at the end of `__init__` — runs every adapter's `setup()` in registration order, right alongside `watchdog.start`. Call `service.stop()` to run `registry.stop_all()`, which tears everything down in reverse order (last set up, first torn down) — a failing `deinit()` is logged and skipped rather than aborting the rest of shutdown, the same failure-tolerant rule `BaseAdapter.deinit()` itself follows.

This is exactly how `main.py`'s `start()` wires the two reference adapters into the boot path today:

```python
def start():
    adapters = [
        ("dht22", DHT22Adapter(pin=setting.DHT22_PIN)),
        ("relay", RelayAdapter(pin=setting.RELAY_PIN)),
    ]
    publish = PublishService(adapters=adapters)
    publish.run()
```

A new adapter follows the same two-line addition: import it, add `(name, YourAdapter(...))` to the `adapters` list.

## Scheduling periodic reads with PollScheduler

`setup()`/`deinit()` cover lifecycle, not read cadence — a `PublishService.run()` loop ticks every second (`time.sleep(1)`), which is too often to poll most sensors. `PollScheduler` (`app/services/poll_scheduler.py`) gates reads to a per-adapter interval:

```python
from app.services.poll_scheduler import PollScheduler

scheduler = PollScheduler(interval_seconds=30)  # default cadence
scheduler.register("dht22", interval_seconds=60)  # override for one name

# inside the run loop, once per tick:
reading = scheduler.poll("dht22", dht22.read)
if reading is not None:
    temperature, humidity = reading
```

`poll(name, read)` calls `read()` and records the timestamp only when `is_due(name)` is true; otherwise it returns `None` without calling `read()`. Each registered name tracks its own last-polled time independently, so a fast-changing sensor and a slow one can share one scheduler with different cadences.

`PublishService.publish_message(message)` expects a `str`. Adapter `read()` shapes vary (`DHT22Adapter.read()` returns a bare tuple, an actuator/indicator returns bool/int), so there's no single dict shape to standardize at the adapter level — `to_payload(**fields)` (`app/adapters/payload.py`) is the one place that turns named reading fields into a JSON string:

```python
from app.adapters.payload import to_payload

reading = scheduler.poll("dht22", dht22.read)
if reading is not None:
    temperature, humidity = reading
    publish.publish_message(to_payload(temperature=temperature, humidity=humidity))
```

Neither `PollScheduler` nor `to_payload` is wired into `PublishService.run()`'s loop automatically — `run()` still publishes whatever static `message` string it's given. Both are standalone building blocks for a custom run loop or a `run()` override, the same way `PubSubService` is a standalone building block rather than something the composition root wires in for you.

## Bench-testing on real hardware

Before wiring a new adapter into a run loop, verify it against real hardware with the CLI: `python tinker.py device test-adapter app.adapters.actuators.relay.RelayAdapter` runs the adapter's `setup()` / `read()` (if present) / `deinit()` cycle on-device via `mpremote exec` and prints the result. The adapter's module must already be on the device (`tinker.py upload` first). Full option reference: [tinker.md#device-test-adapter](tinker.md#device-test-adapter).

## Testing against conftest.py's stubs

`tests/conftest.py` stubs every MicroPython-only module your adapter might import:

```python
for _name in ("network", "umqtt", "umqtt.simple", "machine", "esp32", "dht"):
    sys.modules.setdefault(_name, MagicMock())
```

If your adapter imports a module not in that tuple (another sensor library, `esp32` submodules, etc.), add its name to the tuple first — otherwise every test in the suite fails at collection, not just the ones for your adapter.

Test file convention, mirroring `test_relay_adapter.py`/`test_dht22_adapter.py`/`test_led_adapter.py`:

- Plain `test_<behavior>` functions, no classes.
- A `make_<adapter>(...)` factory instead of a shared fixture.
- `mocker.patch("machine.Pin")` / `mocker.patch("dht.DHT22")` — patch at the stub's own module (`machine.Pin`), not at `app.adapters.sensors.dht22.machine.Pin`, since the adapter does `import machine` rather than `from machine import Pin`.
- Cover, per adapter: `setup()` success and failure, each public method's available/unavailable branches, and `deinit()` called both after `setup()` never ran and after it succeeded.

```python
from app.adapters.actuators.relay import RelayAdapter


def make_adapter(pin=5, active_high=True):
    return RelayAdapter(pin=pin, active_high=active_high)


def test_setup_marks_available_and_starts_off(mocker):
    mock_pin_cls = mocker.patch("machine.Pin")

    adapter = make_adapter(pin=12)
    adapter.setup()

    assert adapter.available is True
    mock_pin_cls.assert_called_once_with(12, mock_pin_cls.OUT)
```

If the adapter gets wired into `PublishService`/`SubscribeService` via `adapters=[...]`, also check `tests/unit/test_publish_service.py`'s `test_adapters_are_registered_and_setup_by_registry` and `test_stop_tears_down_adapters_in_reverse_order` for how to assert on registration/teardown ordering at the service level.

Run with coverage and close every gap it shows — a missed line on an adapter is almost always the `except` branch of `setup()` or an unavailable-state no-op:

```shell
pytest --cov=app --cov-report=term-missing tests/unit/test_<your_adapter>.py
```

---

## Worked example: RelayAdapter

`app/adapters/actuators/relay.py` end to end, annotated against the steps above:

```python
import machine

from app.adapters.base import BaseAdapter


class RelayAdapter(BaseAdapter):
    def __init__(self, pin=5, active_high=True):        # Step 2: explicit args, no side effects
        self.pin = pin
        self.active_high = active_high
        self._relay = None
        self._on = False

    def setup(self):                                     # Step 3: hardware init, try/except
        try:
            self._relay = machine.Pin(self.pin, machine.Pin.OUT)
            self._available = True
            self.off()
        except Exception as e:
            print("Failed to setup relay:", e)
            self._relay = None
            self._available = False

    def on(self):                                         # Step 4: guard on _available
        if not self._available:
            return
        self._relay.value(1 if self.active_high else 0)
        self._on = True

    def off(self):
        if not self._available:
            return
        self._relay.value(0 if self.active_high else 1)
        self._on = False

    def toggle(self):
        if not self._available:
            return
        self.off() if self._on else self.on()

    def is_on(self):
        return self._on

    def deinit(self):                                     # Step 5: unconditional reset
        self._relay = None
        self._available = False
        self._on = False
```

Its test file, `tests/unit/test_relay_adapter.py`, has 12 tests covering setup success/failure, `on`/`off`/`toggle` under both active-high and active-low wiring, all three no-op on unavailable, and `deinit()` from both a never-set-up and a set-up state — that's the coverage bar to match for a new adapter. To bring it into a run loop: `PublishService(adapters=[("relay", relay)])`, which calls `relay.setup()` during construction and `relay.deinit()` when `service.stop()` runs.

---

## Checklist

- [ ] Subclass `BaseAdapter`, file placed under `app/adapters/{sensors,actuators,indicators}/`.
- [ ] Constructor takes explicit named args with defaults, no hardware access.
- [ ] `setup()` wraps hardware init in `try`/`except`, sets `_available`, never raises.
- [ ] Adapter-specific methods guard on `self.available` / `self._available`.
- [ ] `deinit()` unconditionally resets handles and `_available`, safe from any state.
- [ ] New config values (if any) added in all three places (`device_config.json.example`, `Setting.__init__`, construction site).
- [ ] New MicroPython-only imports added to the stub tuple in `tests/conftest.py`.
- [ ] Bench-tested on real hardware with `tinker.py device test-adapter` before wiring into a run loop.
- [ ] If wired into `PublishService`/`SubscribeService`, passed via `adapters=[(name, adapter), ...]` and, if read periodically, gated through `PollScheduler`.
- [ ] Test file covers setup success/failure, each method's available/unavailable branches, and `deinit()` from both states.
- [ ] `pytest --cov=app --cov-report=term-missing` shows no gaps in the new adapter file.
</content>
