# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `PublishService` run loop now logs a `tick` heartbeat (debug level) each cycle with
  current wifi connection state, so setting `log_level: debug` gives serial proof the
  device loop is alive even when `mqtt_enabled` is off and nothing else prints.
- Configurable `log_level` (debug/info/warning/error) to filter `LogService` output by
  minimum severity.
- `PublishService`/`SubscribeService` now publish `HealthCheckService.report()`
  periodically to a dedicated MQTT topic (`health_report_enabled`,
  `health_report_interval_seconds`, `health_report_topic`) so a fleet dashboard can see
  live device health.
- `ErrorHandlerService.guard()` and the `PublishService`/`SubscribeService` run loops now
  log a full stack trace (`sys.print_exception` on-device, exception type + args as a host
  fallback) alongside every unhandled exception, so field crashes are debuggable without a
  live serial session.
- `CrashLogService` persists the final unhandled exception, memory-monitor restart, or
  boot-loop reset to a small guard file (`crash_log_enabled`, `crash_log_path`, mirroring
  `BootLoopGuard`'s `boot_state.json` pattern) before the device resets. `ResetService`
  reads and logs it as `crash_log_recovered` on the next boot, then clears it, so the log
  leading up to a reset survives for post-mortem retrieval.
- `MetricsService` tracks uptime plus published/received message and error counters,
  incremented by `PublishService`/`SubscribeService` on every publish, inbound message,
  and unhandled exception, and surfaced in `HealthCheckService.report()`'s `metrics` key
  alongside the existing health payload.
- `tinker.py device health` fetches and prints a `HealthCheckService` report from the
  device over `mpremote exec` (same pattern as the `device info` "Reset Reason" row), so
  the current health/metrics snapshot can be read without a full MQTT subscriber.

### Changed
- `tinker.py device ls`, `device tree`, `device info` (firmware read), `device health`,
  `device rm`, `device mkdir`, `device test-adapter`, and `upload` now talk to the device
  directly over a raw-REPL serial connection (`device_transport.py`'s new
  `DeviceTransport`) instead of shelling out to the `mpremote` CLI, and no longer require
  `mpremote` on `PATH`. `download`, `provision`, `watch`, `fleet push`, `device repl`,
  and `device logs`/`monitor` still use `mpremote`. All of them enter raw REPL without a
  soft reset, since a soft reset on firmware with a permanently-running `main.py` (like
  this project's `PublishService.run()`) hangs the handshake waiting for a prompt that
  never returns; raw-REPL entry retries with the same linear backoff `upload --reset`
  used to reserve for reset races, now applied on every attempt (previously a plain
  `upload` with no `--reset` got exactly one try). `upload` also now prints each file as
  it's sent (`[i/N] local -> remote`), and its recursive directory walk creates remote
  subdirectories as it goes. `device info`'s MicroPython/Reset Reason rows are read in
  one batched raw-REPL session instead of two separate `mpremote exec` calls, and now
  report a single `unavailable (device unresponsive)` instead of distinguishing a timeout
  from a plain failure. `device mkdir` on an already-existing directory now succeeds
  silently instead of erroring.

### Fixed
- `tinker.py watch` no longer errors with `'mpremote' not found on PATH` on a machine
  without `mpremote` installed. It only ever calls `build()` and `upload()` internally,
  and `upload` stopped needing `mpremote` earlier in this changeset - the check was
  stale and blocked `watch` even though it would have worked.

### Removed
- `tinker.py upload`'s `--resume` flag. It existed to skip mpremote's soft-reset step;
  raw-REPL entry never soft-resets now, so every `upload` already does what `--resume`
  used to - passing the old flag is a CLI error.

## [0.1.0] - 2026-08-08

### Added
- Initial release of the Microweaver framework: WiFi/MQTT/watchdog services,
  OTA update service, safe-mode remote recovery, and the `tinker.py` CLI.

[Unreleased]: https://github.com/nerdmonkey/microweaver-framework/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/nerdmonkey/microweaver-framework/releases/tag/v0.1.0
