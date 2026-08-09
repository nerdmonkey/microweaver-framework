# Reliability & Recovery Guide

Microweaver ships four cooperating services that keep a deployed device alive without operator intervention, and a documented fallback path for when they can't: the [hardware watchdog](#hardware-watchdog), [boot-loop protection](#boot-loop-protection), [safe mode](#safe-mode), and manual [recovery procedures](#recovery-procedures) for a device that won't come back on its own.

- [Overview](#overview)
- [Hardware watchdog](#hardware-watchdog)
- [Boot-loop protection](#boot-loop-protection)
- [Safe mode](#safe-mode)
- [Reset reason logging](#reset-reason-logging)
- [Recovery procedures](#recovery-procedures)
  - [Device stuck in safe mode](#device-stuck-in-safe-mode)
  - [Device stuck in a hard crash loop (no boot-loop protection)](#device-stuck-in-a-hard-crash-loop-no-boot-loop-protection)
  - [Clearing boot-loop state manually](#clearing-boot-loop-state-manually)
- [Related reliability services](#related-reliability-services)
- [Configuration reference](#configuration-reference)

## Overview

The four pieces fit together in one flow:

```
boot.py -> _boot.py (ResetService.read, BootLoopGuard.check)
              |
              +-- boot loop detected --> main.start_safe_mode() --> SafeModeService.run()
              |
              +-- otherwise -----------> main.start() --> PublishService/SubscribeService.run()
                                              |
                                              +-- WatchdogService.feed() every loop iteration
                                              +-- BootLoopGuard.confirm() after a successful connect
```

A watchdog catches a *hung* device (loop stops feeding it); boot-loop protection catches a device that *resets repeatedly* without ever reaching a healthy state; safe mode is the parking spot a boot-looping device lands in instead of crashing forever; reset-reason logging tells you which of these actually happened after the fact.

All four are opt-in via `device_config.json` and default to disabled/permissive so a stock checkout still boots.

## Hardware watchdog

`WatchdogService` (`app/services/watchdog.py`) wraps `machine.WDT`.

```python
class WatchdogService:
    def __init__(self, timeout_ms=8000): ...
    def start(self):   # creates the WDT, must be called once
    def feed(self):     # pets it; no-op if start() hasn't run
```

`PublishService`/`SubscribeService` construct it when `WATCHDOG_ENABLED` is true and call `start()` in their constructor, passing it into `MqttConnection` (`app/services/mqtt.py`). It gets fed from two places: inside `MqttConnection.connect()`'s reconnect retry loop (`app/services/mqtt.py:34-35`, so a broker that's slow or unreachable can't starve it) and once per iteration of the main run loop (`app/services/publish.py:95-96`). If either loop stops making progress — a hang in MQTT I/O, a wedged sensor read, an infinite exception retry — the ESP32's hardware watchdog fires and hard-resets the chip after `WATCHDOG_TIMEOUT_MS` with no feed.

There is no software way to "catch" a watchdog reset before it happens; the only response is to make sure `feed()` sits inside whatever loop can block, and to size `watchdog_timeout_ms` above your slowest expected legitimate operation (MQTT keepalive, WiFi reconnect) so it doesn't trip on normal backoff delays.

## Boot-loop protection

`BootLoopGuard` (`app/services/bootloop.py`) persists an attempt counter to a JSON file (`boot_state.json` by default) across reboots:

- `check()` — called once per boot in `_boot.py:15-20`, *before* `main` is imported. Increments the persisted counter and returns `True` once it exceeds `max_attempts`.
- `confirm()` — called by `PublishService.run()` (`app/services/publish.py:91-92`) right after a successful MQTT connect. Resets the counter to `0`.

So the counter only clears once the device has proven it can reach a healthy state, not just that it booted. A device that boots but immediately crashes before connecting keeps incrementing the counter on every reset until it trips.

When `check()` returns `True`, `_boot.py` prints `BOOT: boot-loop detected, entering safe mode` and calls `main.start_safe_mode()` instead of `main.start()` — the normal application services never start for that boot.

If `boot_loop_protection_enabled` is `false` (the default), `check()`/`confirm()` are no-ops and the counter is never written.

## Safe mode

`SafeModeService` (`app/services/safe_mode.py`) is intentionally minimal:

```python
def run(self):
    print("SAFE MODE: user services disabled, awaiting recovery/reflash")
    while True:
        time.sleep(self.sleep_seconds)
```

It does not retry the normal application, does not touch WiFi/MQTT, and does not exit on its own — it's a deliberate dead end. This keeps a misconfigured or crash-looping device from hammering a broker or WiFi network indefinitely, and keeps it reachable over serial/USB for recovery instead of continuously rebooting. `safe_mode_sleep_seconds` only controls how chatty the idle loop is; it has no effect on how the device leaves safe mode (see [Recovery procedures](#recovery-procedures)).

## Reset reason logging

`ResetService` (`app/services/reset.py`) reads the portable MicroPython
`machine.reset_cause()` API once per boot (`_boot.py:13`, before the boot-loop
check) and logs it via `LogService`. Reset causes map to short labels:

| Label | Meaning |
|---|---|
| `power_on` | Power applied / power-on reset |
| `software` | MicroPython soft reset (`SOFT_RESET`) |
| `watchdog` | Hardware watchdog fired (`WDT_RESET`) |
| `deep_sleep` | Woke from deep sleep |
| `hard_reset` | Hard reset (`HARD_RESET`), which can represent a software hard reset, panic, or external reset |
| `unknown` | Cause not in the known set |

The ESP32 port folds brownouts into `PWRON_RESET`, so they appear as
`power_on`; it also folds software hard resets, panics, and external resets into
`HARD_RESET`. The portable API cannot distinguish those lower-level causes.

A `watchdog` reason is logged at `warning` level; everything else at `info`.
This is the first thing to check when diagnosing *why* a device is boot-looping
-- repeated `watchdog` entries point at a hang rather than an ordinary reboot.

## Recovery procedures

### Device stuck in safe mode

A device printing `SAFE MODE: user services disabled, awaiting recovery/reflash` on a repeating interval has tripped boot-loop protection. It will not recover on its own — safe mode never calls `main.start()`.

1. Connect over serial (e.g. `mpremote connect <port>` or `python tinker.py device info`) and confirm the device is in safe mode from the printed output.
2. Pull the reset-reason and boot-loop history to diagnose *why* it looped, rather than just clearing state and reflashing blind:
   - `mpremote connect <port> cat boot_state.json` — shows the last recorded `attempts` count.
   - Recent `LogService` output on the serial console shows the `reset` / `watchdog_trip` events leading up to the loop.
3. Fix the underlying cause if one is evident (bad WiFi/MQTT credentials in `device_config.json`, a crashing sensor driver, a firmware bug) — clearing the counter without fixing the cause just spends `boot_loop_max_attempts` boots getting back to safe mode.
4. Clear the boot-loop counter (see [below](#clearing-boot-loop-state-manually)) and reset the device (`python tinker.py device reset` or power-cycle).
5. Watch the next boot connect successfully — `PublishService`/`SubscribeService` call `BootLoopGuard.confirm()` right after connecting, which is what actually keeps it out of safe mode going forward.

### Device stuck in a hard crash loop (no boot-loop protection)

If `boot_loop_protection_enabled` is `false`, a crashing device just reboots forever with no safe-mode backstop. There's no software recovery path in this state — the fix is:

1. Confirm the crash from serial output or reset-reason logs.
2. Flip `boot_loop_protection_enabled` to `true` in `device_config.json` so future crash loops land in safe mode instead of looping indefinitely (see [Configuration reference](#configuration-reference)).
3. Reflash/redeploy with `python tinker.py upload` once the underlying bug is fixed.

### Clearing boot-loop state manually

`boot_state.json` is a plain JSON file (`{"attempts": N}`) at the path set by `boot_loop_state_path` (default `boot_state.json`), on the device's own filesystem. To clear it without waiting for a successful `confirm()`:

```shell
mpremote connect <port> rm boot_state.json
```

Deleting the file is equivalent to `{"attempts": 0}` — `BootLoopGuard._read()` treats a missing/unreadable file as `0` (`app/services/bootloop.py:38-43`). You can also overwrite it directly with `mpremote connect <port> cp` if you'd rather set a specific count.

## Related reliability services

These aren't part of the watchdog/boot-loop/safe-mode chain but feed the same "detect and self-heal" story and are useful context when investigating a recovery:

- **`MemoryMonitorService`** (`app/services/memory_monitor.py`) — checks `gc.mem_free()` against `memory_monitor_threshold_bytes` on every run-loop iteration; `memory_monitor_action` of `restart` calls `machine.reset()` directly, which is one more source of `software`-labeled resets to rule out when reading reset-reason logs.
- **`HealthCheckService`** + **`ServiceRestartService`** (`app/services/health.py`, `app/services/service_restart.py`) — poll registered checks (WiFi/MQTT connectivity) and restart individual unhealthy services in-process, up to `service_restart_max_attempts`, without a full device reset. This is the layer that runs *before* things escalate to a watchdog trip or boot loop.

## Configuration reference

All keys live in `device_config.json` (see `device_config.json.example`); every one has a safe default and none are required for the device to boot.

| Key | Default | Purpose |
|---|---|---|
| `watchdog_enabled` | `false` | Enables `WatchdogService` |
| `watchdog_timeout_ms` | `8000` | Hardware watchdog timeout before a forced reset |
| `boot_loop_protection_enabled` | `false` | Enables `BootLoopGuard` tracking |
| `boot_loop_max_attempts` | `5` | Consecutive unconfirmed boots before safe mode triggers |
| `boot_loop_state_path` | `boot_state.json` | Path to the persisted attempt counter |
| `safe_mode_sleep_seconds` | `5` | Idle interval for the safe-mode holding loop |
| `memory_monitor_enabled` | `false` | Enables `MemoryMonitorService` |
| `memory_monitor_threshold_bytes` | `10000` | Free-heap floor before `memory_monitor_action` fires |
| `memory_monitor_action` | `log` | `log`, `warn`, or `restart` |
| `health_check_enabled` | `false` | Enables `HealthCheckService` polling |
| `health_check_interval_seconds` | `30` | Minimum seconds between health check polls |
| `service_restart_enabled` | `false` | Enables `ServiceRestartService` (requires health checks) |
| `service_restart_max_attempts` | `3` | Restart attempts per service before giving up |
| `log_format` | `json` | `json` or `kv` output format for all `LogService` events |
