# Observability Guide

Microweaver ships four cooperating pieces that answer "what is this device doing right now, and what happened right before it died": structured [logging](#logging), MQTT-published [health reports](#health-reports), in-memory [metrics counters](#metrics), and an on-device [crash log](#crash-log) that survives a reset.

- [Overview](#overview)
- [Logging](#logging)
  - [Log format and levels](#log-format-and-levels)
  - [Remote log-level override](#remote-log-level-override)
- [Metrics](#metrics)
- [Health reports](#health-reports)
  - [Health checks](#health-checks)
  - [MQTT health-report topic](#mqtt-health-report-topic)
  - [Pulling a health snapshot over serial](#pulling-a-health-snapshot-over-serial)
- [Crash log](#crash-log)
  - [What gets written](#what-gets-written)
  - [Retrieving a crash log after a reset](#retrieving-a-crash-log-after-a-reset)
- [Configuration reference](#configuration-reference)

## Overview

All four pieces are constructed together in `PublishService`/`SubscribeService` (`app/services/publish.py:32-45`, `app/services/subscribe.py:34-47`) and wired through the same `ErrorHandlerService`, so any unhandled exception in a run loop produces one `LogService` entry, one `CrashLogService.write()`, and one `MetricsService.record_error()` — three views of the same event instead of three separate mechanisms to configure:

```
LogService.log()        -> stdout, one line per event (json or kv)
MetricsService.record_*() -> in-memory counters, reset on every boot
CrashLogService.write()  -> crash.json on the device filesystem, survives a reset
HealthCheckService.report() -> {app_version, healthy, checks, metrics}, published to MQTT
```

Metrics are folded into the health report (`HealthCheckService.report()`, `app/services/health.py:78-86`), so a single MQTT message covers both "is it healthy" and "how much traffic has it handled since boot."

## Logging

`LogService` (`app/services/logger.py`) is the only logging mechanism in the codebase — there's no `logging` module dependency, just `print()`.

### Log format and levels

```python
class LogService:
    def __init__(self, format="json", level="info"): ...
    def log(self, event, level="info", **fields): ...
```

- `format`: `json` (default) prints `json.dumps(entry)`; `kv` prints `key=value` pairs, quoting any value containing a space.
- `level`: one of `debug` (10), `info` (20, default), `warning` (30), `error` (40). A call to `log()` below the configured level is dropped before printing.
- Every entry always carries `event`, `level`, and `ts` (`time.time()`), plus whatever `**fields` the caller passes — e.g. `logger.log("health_check_failed", level="warning", service=name, error=str(e))` in `app/services/health.py:65-70`.

`PublishService`/`SubscribeService` construct their `LogService` from `LOG_FORMAT`/`LOG_LEVEL` (`app/services/publish.py:32-34`); every other service that logs (`HealthCheckService`, `ResetService`, `ErrorHandlerService`, …) takes a `logger=` argument and defaults to `LogService()` if none is passed, so they inherit whatever format/level the caller configured.

### Remote log-level override

If `log_level_override_enabled` is `true`, `RuntimeService` subscribes to `log_level_topic` in addition to its normal topics (`app/services/runtime.py:149-154`) and routes incoming messages to `_handle_log_level_message` (`app/services/runtime.py:258-266`):

```python
def _handle_log_level_message(self, topic, message):
    requested = message.decode().strip().lower()
    if self.log_service.set_level(requested):
        self.log_service.log("log_level_overridden", level="info", new_level=requested)
    else:
        self.log_service.log("log_level_override_rejected", level="warning", requested=requested)
```

Publish a plain-text payload (`debug`, `info`, `warning`, or `error`) to `log_level_topic` to change verbosity on a running device without redeploying — useful for turning on `debug` output while chasing an intermittent issue, then dialing it back down. An unrecognized payload is rejected and logged at `warning`, leaving the current level unchanged.

## Metrics

`MetricsService` (`app/services/metrics.py`) is a plain in-memory counter object, reset every time it's constructed (i.e. every boot — nothing is persisted):

```python
class MetricsService:
    def __init__(self): ...        # start_time = now
    def record_publish(self): ...  # messages_published += 1
    def record_message(self): ...  # messages_received += 1
    def record_error(self): ...    # errors += 1
    def uptime_seconds(self): ...  # time.time() - start_time
    def snapshot(self): ...        # dict of all of the above
```

`PublishService`/`SubscribeService` call `record_publish()`/`record_error()` around every `_publish()` (`app/services/publish.py:198-201`) and `record_message()` on every incoming MQTT message (`app/services/subscribe.py:164`, via `RuntimeService.on_message`). There's one `MetricsService` instance per service object — a device running both publish and subscribe loops has two independent counters, not one shared total.

`snapshot()` is what ends up under `"metrics"` in a health report (see below); there's no separate metrics-only topic or command.

## Health reports

### Health checks

`HealthCheckService` (`app/services/health.py`) polls a dict of named zero-arg callables (`checks`) no more often than `interval_seconds`, and records `{healthy, error, checked_at}` per check. `PublishService`/`SubscribeService` register `wifi` (`WiFiService.is_connected`) and, if `MQTT_ENABLED`, `mqtt` (`self.client is not None`) — see `app/services/publish.py:141-147`. A check that raises is treated as unhealthy with the exception message captured in `error`, and logged at `warning` via `health_check_failed`.

If `service_restart_enabled` is also `true`, `ServiceRestartService` (`app/services/service_restart.py`) uses the same check results to retry individual unhealthy services in-process — see [reliability.md](reliability.md#related-reliability-services) for that piece; this doc only covers the reporting side.

### MQTT health-report topic

If `health_report_enabled` is `true` and MQTT is enabled, `PublishService`/`SubscribeService` register a `PollScheduler` tick at `health_report_interval_seconds` (`app/services/publish.py:159-171`) that calls `_publish_health_report()`:

```python
def _publish_health_report(self):
    self._publish(self.health_report_topic, json.dumps(self.health_check_service.report()))
```

The payload is `HealthCheckService.report()`:

```json
{
  "app_version": "0.1.0",
  "healthy": true,
  "checks": {
    "wifi": {"healthy": true, "error": null, "checked_at": 1730000000.0},
    "mqtt": {"healthy": true, "error": null, "checked_at": 1730000000.0}
  },
  "metrics": {
    "uptime_seconds": 3600.2,
    "messages_published": 42,
    "messages_received": 7,
    "errors": 0
  }
}
```

Default topic is `device/{mqtt_client_id}/health` (`config/app.py`'s `HEALTH_REPORT_TOPIC` default); override with `health_report_topic` in `device_config.json`. `health_report_enabled` requires `health_check_enabled` to actually populate `checks` — with health checks off, `report()` still publishes but `checks` stays empty and `healthy` is trivially `True` (`all()` over an empty dict).

### Pulling a health snapshot over serial

`python tinker.py device health [--port <port>]` doesn't need MQTT or a running subscriber — it builds a fresh `WiFiService`/`MetricsService`/`HealthCheckService` on-device over the raw REPL, polls it once, and prints the JSON report (`tinker.py:1050-1090`). Because it's a fresh `MetricsService` instance, the counters in that output start from zero, not the running loop's accumulated totals — use the MQTT health report (or `python tinker.py device logs`) if you need the live loop's numbers.

## Crash log

### What gets written

`CrashLogService` (`app/services/crash_log.py`) persists a single JSON entry to a file on the device (`crash_log_path`, default `crash.json`) — not a growing log, just the most recent crash. `ErrorHandlerService.guard()` (`app/services/error_handler.py:35-56`) is the main writer: any exception it catches gets `logger.log("unhandled_exception", ...)`, `crash_log.write("unhandled_exception", context=..., error=..., trace=...)`, and `metrics.record_error()`, in that order. `_boot.py` also writes a `boot_loop_reset` entry right before an OTA-rollback-triggered reset, so a rollback shows up in the next boot's crash-log recovery too.

If the serialized entry would exceed `crash_log_max_bytes`, `_shrink()` truncates the longest string field(s) (typically `trace`) with a `...[truncated]` marker until it fits, rather than dropping the write entirely (`app/services/crash_log.py:30-57`). `crash_log_enabled` defaults to `false`; `write()`/`clear()` are no-ops when disabled, and a full disk or filesystem error is caught and printed, never raised.

### Retrieving a crash log after a reset

Two paths, depending on whether the device has already rebooted since the crash:

**Automatic — already rebooted.** `ResetService.read()` calls `_recover_crash_log()` on every boot, *before* the boot-loop check: if `crash.json` exists, its contents are logged as a single `crash_log_recovered` event at `error` level (with the original `event` field renamed to `original_event`) and the file is then cleared. This means a persisted crash log only survives from the moment of the crash until the *next* boot — check the serial console (`python tinker.py device logs`) or your MQTT log sink for a `crash_log_recovered` entry rather than expecting `crash.json` to still be on disk after a successful reboot.

**Manual — device hasn't rebooted, or you want the raw file.** Read it directly off the device filesystem before it gets recovered/cleared:

```shell
mpremote connect <port> cat crash.json
```

This is the same pattern as reading `boot_state.json` for boot-loop history (see [reliability.md](reliability.md#clearing-boot-loop-state-manually)) — `crash.json` is a plain file on the device's own filesystem, not a special-cased artifact.

## Configuration reference

All keys live in `device_config.json` (see `device_config.json.example`); every one has a safe default and none are required for the device to boot.

| Key | Default | Purpose |
|---|---|---|
| `log_format` | `json` | `json` or `kv` output format for all `LogService` events |
| `log_level` | `info` | Minimum level printed: `debug`, `info`, `warning`, `error` |
| `log_level_override_enabled` | `false` | Enables the `log_level_topic` remote override |
| `log_level_topic` | `device/{mqtt_client_id}/log-level` | Topic for changing `log_level` at runtime |
| `health_check_enabled` | `false` | Enables `HealthCheckService` polling |
| `health_check_interval_seconds` | `30` | Minimum seconds between health check polls |
| `health_report_enabled` | `false` | Enables periodic MQTT publish of the health report |
| `health_report_interval_seconds` | `60` | Interval between health-report publishes |
| `health_report_topic` | `device/{mqtt_client_id}/health` | Topic the health report is published to |
| `crash_log_enabled` | `false` | Enables `CrashLogService` writes |
| `crash_log_path` | `crash.json` | Path to the persisted crash entry on-device |
| `crash_log_max_bytes` | `4096` | Size ceiling before the largest string field gets truncated |
