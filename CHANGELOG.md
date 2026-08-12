# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `ntp_enabled`/`ntp_server`/`ntp_sync_timeout_seconds` config keys (default
  `true`/`pool.ntp.org`/`5`) plus `NtpSyncService` (`app/services/ntp.py`),
  synced once per successful MQTT connect in `RuntimeService.run()`. Without
  this the ESP32's clock never leaves MicroPython's 2000-01-01 epoch, so
  every publish payload's `timestamp`/`timestamp_local` were meaningless
  (e.g. `2000-01-01T00:01:09+00:00`-style values instead of real time).

### Fixed
- `DHT22Adapter`/`DHT11Adapter` now carry a `read_interval_seconds` class
  attribute (`2`/`1`, per datasheet minimums) that `RuntimeService`'s
  publish scheduler picks up instead of its 1-second default — polling a
  DHT22 faster than its 2-second minimum sampling period returned garbage
  readings (e.g. 870°C / 2432% humidity) instead of a fresh measurement.
- `main.py` no longer unconditionally imports `OLEDAdapter`/
  `PotentiometerAdapter`/`RotaryAngleAdapter` (and the framebuf-heavy
  `app/libs/ssd1306.py` driver they pull in) on every boot regardless of
  whether `oled_enabled`/`potentiometer_enabled`/`rotary_angle_enabled` is
  set — the extra heap load from those imports could starve the ESP32 WiFi
  driver's rx-buffer allocation, surfacing as `OSError: WiFi Out of Memory`
  out of `WiFiService.__init__` on boot. Imports are now deferred until
  each adapter's `_enabled` flag confirms it's actually wired up.

### Added
- `device_name`/`timezone`/`timezone_offset_minutes` config keys, plus an
  envelope wrapping every adapter publish payload with `action`, `client_id`,
  `ok`, `timestamp`, `timestamp_local`, `device`, and `timezone` fields
  around the existing reading fields (`RuntimeService._envelope`,
  `app/services/runtime.py`) — matches the shape expected by downstream
  consumers instead of publishing bare `{temperature, humidity}`-style
  payloads.
- `dht_enabled` and `relay_enabled` config keys (default `true`, matching
  prior always-on behavior) let a device be provisioned without a DHT sensor
  or relay wired up, instead of `main.py` unconditionally constructing both
  adapters on every boot.
- `oled_enabled` config key (default `false`) plus `oled_sda_pin`/
  `oled_scl_pin`/`oled_i2c_addr`/`oled_width`/`oled_height` wire a new
  `OLEDAdapter` (`app/adapters/indicators/oled.py`) — an SSD1306 128x64 I2C
  display on ESP32's default SDA=21/SCL=22 pins — into `main.py` as an MQTT
  subscribe adapter, with `on()`/`off()`/`toggle()` driven by
  `RuntimeService`'s existing command dispatch and `show_text()`/`clear()`
  for writing status lines to the panel. The SSD1306 driver is vendored
  verbatim from micropython-lib at `app/libs/ssd1306.py`, imported as
  `from app.libs import ssd1306` and deployed alongside the rest of `app/`.
- `tinker.py topics` command lists the configured MQTT publish/subscribe
  topics from `device_config.json` (falling back to `device_config.json.example`
  if not yet provisioned) alongside which adapter(s) each one drives,
  replicating `RuntimeService._resolve_command_adapter`'s exact routing rules
  (exact match, topic-suffix match, single-adapter fallback) and flagging
  unmatched subscribe topics or the case where no subscribe adapters are
  enabled at all.
- `potentiometer_enabled`/`potentiometer_pin` and `rotary_angle_enabled`/
  `rotary_angle_pin` config keys (default `false`, pin `34`) wire two new
  ADC-based publish adapters — `PotentiometerAdapter` and
  `RotaryAngleAdapter` (`app/adapters/sensors/potentiometer.py`,
  `app/adapters/sensors/rotary_angle.py`) — into `main.py`. Both read a
  variable-resistor voltage divider via `machine.ADC` (`ATTN_11DB`,
  `read_u16()`) and report position as a 0–100 percentage.

### Changed
- `mqtt_topic_pub` now accepts one or more topics (comma-separated string or
  JSON array), matching `mqtt_topic_sub`'s existing list support, instead of
  a single fixed publish topic shared unconditionally by every sensor.
  `RuntimeService._resolve_publish_topic()` routes each publish adapter's
  reading using the same rules `_resolve_command_adapter()` already uses for
  subscribe topics (exact match, topic-suffix match, single-topic fallback
  shared by all adapters), and skips + logs a warning for a reading whose
  adapter name matches no configured topic instead of silently misdelivering
  it. A single configured topic (the existing default) is still shared by
  every publish adapter, so existing `device_config.json` files behave
  identically. `RuntimeService.publish_message()` and
  `PublishService.publish_message()` (`app/services/runtime.py`,
  `app/services/publish.py`) now take the target topic explicitly rather
  than reading a fixed `self.topic`; `tinker.py topics` reports the
  resulting per-adapter pub routing the same way it already does for sub.

### Fixed
- `RuntimeService.run()` now backs off with exponential delay (reset on
  successful reconnect) before retrying after any post-connect failure,
  including a broker-refused subscribe (SUBACK failure), instead of hammering
  the broker in a tight zero-delay reconnect loop. Broker-refused
  subscriptions are also logged with a clearer `subscribe_refused` reason
  (check ACL/permissions) instead of a bare `MQTTException: 128`.
- Hardware-soak backups are now staged atomically and retried after a hard
  reset/readiness probe, so an interrupted raw-REPL download cannot be restored
  or reported as a complete device backup.
- Reset-reason logging now uses MicroPython's supported `machine.reset_cause()`
  API, allowing real ESP32 watchdog resets to be recorded as `watchdog` instead
  of `unknown`.

### Added
- `scripts/hardware_soak.py --ota-local-fixture` now generates and temporarily
  hosts a harmless `boot.py` OTA payload, then verifies real ESP32 download,
  checksum, flash swap, rollback, exact-byte restoration, and transient cleanup
  without requiring a separately published fixture.
- A backup-protected `scripts/hardware_soak.py` release-gate runner records
  real-ESP32 evidence for SoftAP provisioning, HTTP OTA apply/rollback, and
  watchdog-driven boot-loop recovery before v1.0.
- Configurable `publish_interval_seconds` (default 1, matching prior fixed-1s
  behavior) gates how often `PublishService` publishes each tick, so sensor
  readings (e.g. DHT temperature/humidity) can be sent every N seconds instead
  of every tick, independently per device via `device_config.json`.
- `MqttConnection.connect()` now inspects the MQTT CONNACK return code: rc=1/2/4/5
  (bad protocol version, rejected client ID, bad credentials, ACL denial) are
  permanent for the current config and raise `MqttConnectionRejected` instead of
  retrying forever, while rc=3 (server unavailable) and network-level errors keep
  the existing exponential-backoff retry. `PublishService`/`SubscribeService` catch
  the new exception, log a distinct `mqtt_connection_rejected` event, and back off
  for `mqtt_rejection_retry_seconds` (default 300s) before trying again, instead of
  hammering the broker every few seconds with credentials/ACLs that won't change on
  their own.
- `CrashLogService` now caps a persisted crash entry at `crash_log_max_bytes`
  (default 4096, configurable), truncating the largest string field (typically the
  stack trace) so a single write can't consume unbounded flash on-device.
- Remote `log_level` override via MQTT: `RuntimeService` subscribes to
  `log_level_topic` (`log_level_override_enabled`) and applies a valid level to
  `LogService` at runtime for field debugging, reverting to the configured default on
  next reboot.
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
- `tinker.py restore` deploys a previous `backup` folder's contents back onto the device
  - the reverse of `backup`, sharing `deploy`'s raw-REPL transfer path (retries,
  `--reset`, per-file progress) but never persisting its `path` argument to
  `.microweaver`, so restoring from a backup can't silently change what a plain `deploy`
  uploads next time.
- `tinker.py ota build`/`tinker.py ota validate`: `ota build` computes a sha256 for each
  given project file and writes a `dist/ota/<version>/manifest.json` (plus mirrored
  copies of the files, ready to upload as-is to a CDN) in the `{url, sha256}` shape
  `app/services/ota.py`'s `apply_update()` requires; `ota validate` lint-checks a
  manifest's structure (rejecting the checksum-less short form) and optionally
  recomputes checksums against a local `--files-root` to catch drift before shipping an
  OTA release.
- `tinker.py ota diff OLD_MANIFEST NEW_MANIFEST` compares OTA release versions and
  classifies added, removed, content-changed, and URL-only-changed files, with optional
  machine-readable `--json` output for CI and release automation.

### Changed
- `tinker.py upload` renamed to `deploy`; `download` renamed to `backup`, to pair with
  the new `restore` command.
- `tinker.py device ls`, `device tree`, `device info` (firmware read), `device health`,
  `device rm`, `device mkdir`, `device test-adapter`, `deploy`, `backup`, and
  `provision` now talk to the device directly over a raw-REPL serial connection
  (`device_transport.py`'s new `DeviceTransport`) instead of shelling out to the
  `mpremote` CLI, and no longer require `mpremote` on `PATH`. `fleet push`,
  `device repl`, and `device logs`/`monitor` still use `mpremote`. All of them enter raw
  REPL without a soft reset, since a soft reset on firmware with a permanently-running
  `main.py` (like this project's `PublishService.run()`) hangs the handshake waiting for
  a prompt that never returns; raw-REPL entry retries with the same linear backoff
  `deploy --reset` used to reserve for reset races, now applied on every attempt
  (previously a plain `deploy` with no `--reset` got exactly one try). `deploy` and
  `backup` now print each file as it's sent/received (`[i/N] local -> remote` /
  `[i/N] remote -> local`), and `deploy`'s recursive directory walk creates remote
  subdirectories as it goes. `device info`'s MicroPython/Reset Reason rows are read in
  one batched raw-REPL session instead of two separate `mpremote exec` calls, and now
  report a single `unavailable (device unresponsive)` instead of distinguishing a timeout
  from a plain failure. `device mkdir` on an already-existing directory now succeeds
  silently instead of erroring.

### Fixed
- Raw-REPL commands such as `tinker.py deploy` now report a concise, actionable
  error when the configured serial port cannot be opened instead of displaying a
  pyserial traceback when the device is disconnected or its port has changed.
- `tinker.py watch` no longer errors with `'mpremote' not found on PATH` on a machine
  without `mpremote` installed. It only ever calls `build()` and `deploy()` internally,
  and `deploy` stopped needing `mpremote` earlier in this changeset - the check was
  stale and blocked `watch` even though it would have worked.
- `SubscribeService.run()` no longer crashes the device loop when the broker rejects a
  topic subscription (e.g. an ACL/policy denial). `connect_to_mqtt()` moved inside the
  loop's exception handler, so a failed `subscribe()` call is now logged and retried the
  same way a mid-session connection drop already was.
- `PublishService.run()` had the same latent issue: `connect_to_mqtt()` ran outside the
  loop's `try`/`except`, so any exception raised there (previously only theoretical since
  `MqttConnection.connect()` retried forever internally, but now possible via the new
  `MqttConnectionRejected`) would have crashed the device loop uncaught. Moved inside the
  `try` block to match `SubscribeService`.
- `tinker.py provision`'s interactive prompts no longer echo an existing WiFi/MQTT
  password in plaintext as the prompt's `[default]` hint. `hide_input` only masked what
  you typed, not the default value already sitting in `device_config.json`, so every
  secret in that file was printed to the terminal (and scrollback) on every `provision`
  run. Secret fields now show `[unchanged]` instead, and leaving the line blank keeps the
  existing value.
- `main.start()` now runs sensors and relay commands through one `RuntimeService` loop
  with a single MQTT connection, so the DHT22 publisher and relay subscriber share the
  same reconnect/watchdog lifecycle without needing a second MicroPython thread.
- `RuntimeService` now treats MQTT subscribe failures the same way as other connection
  losses, logging them and re-entering the reconnect loop instead of crashing out of
  boot before the retry boundary is reached.
- Temperature sensor selection is now configurable via `dht_sensor_type`
  (`dht11` or `dht22`), so boards using a DHT11 no longer need a code edit to boot
  and publish readings.
- The shared DHT sensor pin config is now named `dht_pin`; `dht22_pin` is still accepted
  as a backward-compatible fallback for older device configs.

### Removed
- `tinker.py deploy`'s `--resume` flag (present when this command was still named
  `upload`). It existed to skip mpremote's soft-reset step; raw-REPL entry never
  soft-resets now, so every `deploy` already does what `--resume` used to - passing the
  old flag is a CLI error.

## [0.1.0] - 2026-08-08

### Added
- Initial release of the Microweaver framework: WiFi/MQTT/watchdog services,
  OTA update service, safe-mode remote recovery, and the `tinker.py` CLI.

[Unreleased]: https://github.com/nerdmonkey/microweaver-framework/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/nerdmonkey/microweaver-framework/releases/tag/v0.1.0
