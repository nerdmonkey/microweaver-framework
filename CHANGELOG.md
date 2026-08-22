# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `tinker.py device config` gained `get`/`set`/`unset` subcommands for
  reading and editing individual `device_config.json` keys without hand-
  editing the file - `set` validates against the same schema `Setting`
  enforces on-device (type, min/max, choices), rejecting unknown keys or
  invalid values before writing; `unset` removes a key so it reverts to
  `Setting`'s built-in default. Bare `device config` keeps its previous
  behaviour as the `show` subcommand's default alias.
- `tinker.py provision` gained an `--id` flag to renew an existing Agnes
  device by its exact device id, bypassing name lookup and the interactive
  picker entirely - mutually exclusive with `--name`. Agnes doesn't enforce
  unique device names, so `--name` alone could register a duplicate device
  instead of renewing the intended one when names collided; `--id` gives an
  unambiguous way to target a renew by hand.
- `tinker.py provision` gained a `--device-name` flag (and matching
  `device_name` prompt) to fill in `device_config.json`'s `device_name`
  key - previously always blank unless hand-edited after provisioning,
  even though `RuntimeService._envelope()` already put it in every publish
  payload's `device` field. Defaults to `--name` (the Agnes registration
  name) when registering a new device via the API, or to the picked
  device's existing Agnes name when renewing one via the device picker,
  when `--device-name` isn't given.
- `RGBAdapter` (`app/adapters/actuators/rgb.py`) drives a 3-channel PWM RGB
  LED (`machine.PWM`, 0-1023 duty) with the same `on()`/`off()`/`toggle()`/
  `is_on()` surface as `RelayAdapter`, wired into `main.py` behind
  `rgb_enabled` (default `false`, matching `relay_enabled`'s pattern) plus
  `rgb_red_pin`/`rgb_green_pin`/`rgb_blue_pin` (default `25`/`26`/`27`) and
  `rgb_topic_suffix` (default `rgb`) - composes
  `devices/{mqtt_username}/commands/rgb` alongside the relay's
  `.../commands/relay`.
- `mqtt_topic_status` config key (default `devices/{mqtt_username}/status`,
  resolved the same way as `mqtt_topic_pub`/`mqtt_topic_sub` at provision
  time) and a `topics_status` `RuntimeService` constructor param: after a
  relay/RGB command (`on`/`off`/`toggle`) executes,
  `RuntimeService._publish_status()` publishes the adapter's resulting
  `is_on()` state to its own `devices/{mqtt_username}/status/{suffix}`
  topic - previously nothing reported an actuator's state back after a
  command, only sensors published anything. Only adapters with an
  `is_on()` method get a status topic (relay, RGB - not OLED).
  `tinker.py topics` gained a third STATUS table alongside PUB/SUB for this.
- `DeviceCertService` (`app/services/device_cert.py`) falls back to the
  claimed `device_cert`/`device_key` (from the registration/claim flow) as
  the MQTT client's mTLS certificate when `mqtt_ssl_cert_path`/
  `mqtt_ssl_key_path` are unset, writing the PEM content to disk
  (`device_cert_path`/`device_key_path`) since `umqtt.simple`'s `ssl_params`
  expects file paths. Resolved lazily inside `MqttConnection.connect()` (only
  when `mqtt_ssl` is on and no explicit cert path is set), so constructing
  the runtime never touches disk on its own. Fixes
  `MBEDTLS_ERR_SSL_FATAL_ALERT_MESSAGE`/`ECONNRESET` connect failures against
  brokers that enforce client certificates for claimed devices, where the
  claimed cert was saved to config but never wired into the MQTT TLS
  handshake.
- `NtpService` (`app/services/ntp.py`) syncs device clock via NTP before the
  TLS handshake when `mqtt_ssl` is enabled, fixing repeated
  `MBEDTLS_ERR_SSL_FATAL_ALERT_MESSAGE`/`ECONNRESET` connect failures caused
  by the ESP32's unset RTC failing certificate validity checks. Enabled by
  default (`ntp_enabled`), configurable via `ntp_host`, `ntp_sync_attempts`,
  `ntp_retry_delay_seconds`.
- `tinker.py profile` command group (`create`/`edit`/`delete`/`list`/`show`/
  `use`) for managing named Agnes API connection profiles (`api_url`,
  `api_key`, `port`, `baud`) saved in `.microweaver`, instead of `--profile`
  only being usable as a bare name for CA-cert lookup. `provision` and
  `fetch-ca-cert` now resolve `--api-url`/`--api-key`/`--ca-cert` from the
  named (or active) profile when not passed explicitly, in CLI flag >
  profile > `.microweaver` `[default]` > hardcoded default order.
  `fetch-ca-cert` now also saves the resolved `api_url` into the
  profile it fetches for. `profile create` also interactively prompts for
  name/`api_url`/`api_key`/`port` when omitted on a TTY (edit shows existing
  values as defaults), and automatically fetches and saves the CA cert for
  any `api_url` it ends up with (a fetch failure only warns, since the
  profile is already saved by that point - retry later with
  `fetch-ca-cert`).
- `tinker.py provision`, when registering via the Agnes API
  (`--api-url`/`--api-key`), now also saves the registration response's cert
  bundle to `./certs/ca.pem`, `client.pem`, and `private.pem` (gitignored),
  mirroring the Agnes project's own tinker.py cert layout - the API only
  returns a device's certs once, at registration time, so this is the only
  chance to keep a local copy of them. When `--name` is omitted on a TTY,
  `provision` now lists existing devices first (Azure-CLI-picker style) so
  you can pick one to renew its cert instead of always registering a new
  device - MQTT credentials in that case still come from CLI flags/prompts
  as before, since renewing only reissues certs, not MQTT credentials. A new
  `--skip-certs` flag opts out of all of this: no `./certs/` write and no
  `device_cert`/`device_key` in `device_config.json`.
- `tinker.py certs download` command: takes an *existing* device's
  `--device-id`, calls `POST /devices/{device_id}/renew-cert` on the Agnes
  API (`--api-url`/`--api-key`, or a saved `--profile`), and saves the
  resulting cert bundle to `./certs/` (or `--out-dir`) - reissues that
  device's certs without registering a new device or touching serial. When
  `--device-id` is omitted on a TTY, lists devices from the API
  (`GET /devices`) and prompts for one by number, Azure-CLI-picker style,
  instead of requiring the ID to already be known.
- `dht_topic_suffix`/`relay_topic_suffix`/`oled_topic_suffix`/
  `potentiometer_topic_suffix`/`rotary_angle_topic_suffix` config keys (each
  defaulting to a short device name, e.g. `dht`, `relay`) let each enabled
  adapter get its own MQTT topic composed from `mqtt_topic_pub`/
  `mqtt_topic_sub` (as a single base) plus the device's suffix, e.g. base
  `data/sensor/room` + suffix `oled` -> `data/sensor/room/oled` — instead of
  every enabled adapter needing a fully spelled-out topic in
  `mqtt_topic_pub`/`mqtt_topic_sub`. `RuntimeService` gained a `topics_pub`
  constructor override (mirrors the existing `topics` override) so `main.py`
  can hand it the composed publish-topic list.
- `tinker.py device config` prints `device_config.json` (falling back to
  `device_config.json.example` when not yet provisioned) as an Azure
  CLI-style key/value table, with secret fields (`wifi_password`,
  `mqtt_password`, `device_key`, `provisioning_ap_password`) masked unless
  `--reveal` is passed.
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
- `tinker.py provision` now writes `mqtt_topic_pub`/`mqtt_topic_sub` with
  the run's resolved `mqtt_username` substituted into any `{mqtt_username}`
  placeholder (e.g. `devices/{mqtt_username}/sensors` ->
  `devices/dev-42/sensors`) instead of an unresolved template, so
  `device_config.json` on disk always holds the real per-device topic - the
  device itself does no substitution. Default `mqtt_topic_pub`/
  `mqtt_topic_sub` (`device_config.json.example`, `PROVISION_FIELDS`,
  `config/app.py`'s fallback) changed from `data/sensor`/`command/control`
  to `devices/{mqtt_username}/sensors`/`devices/{mqtt_username}/commands`,
  matching the Agnes API's own `devices/{id}/...` topic namespace and its
  already-existing per-device ACL auto-provisioning (`devices/{username}/#`)
  and `logger_role`'s wildcard `devices/+/commands/#` publish grant, so
  Agnes's `send_device_command` API can reach a device provisioned this way
  with no Agnes-side changes.
- `tinker.py provision` sets `mqtt_ssl: true` automatically when
  `mqtt_port` is `8883`, since a plaintext connect to Agnes's TLS listener
  fails as `ECONNRESET` at the handshake rather than a clear auth error -
  easy to end up debugging as a broker/cert issue instead of the missing
  flag.
- `tinker.py provision`, when renewing an existing device's cert
  (`--api-url`/`--api-key` with an existing device picked, not a fresh
  registration) and no local `mqtt_username`/`mqtt_password` are already
  known (CLI flags or existing `device_config.json`), now also rotates the
  device's MQTT password via the Agnes API's `POST /devices/{device_id}/
  provision-mqtt` (invalidating the old one) to recover working credentials
  - previously these were left blank, since `renew-cert` itself never
  reissues them and Agnes has no way to return the original password (only
  a hash is stored). Skipped when local credentials are already known, to
  avoid needlessly invalidating a password already in use.
- `tinker.py topic list` gained `--output`/`-o` to export the filtered
  topic rows as an MQTT ACL policy JSON file (`version`, `exported_at`,
  `device_id`, `device_name`, `policy_count`, `policies[]` with
  `topic`/`action`/`enabled`) instead of printing the table - rejects a
  destination that doesn't end in `.json`. `action` is `publish` for
  PUB/STATUS rows and `subscribe` for SUB rows; `enabled` is `false` only
  for the no-adapters-configured placeholder rows.

### Changed
- DHT temperature/humidity now publish as two separate messages on two
  separate topics (`devices/{mqtt_username}/sensors/temperature` and
  `.../humidity`, one `{"value": ...}` payload each) instead of one
  combined `{"temperature": ..., "humidity": ...}` payload on a single
  `dht` topic - `dht_topic_suffix` is replaced by
  `dht_temperature_topic_suffix`/`dht_humidity_topic_suffix` (defaults
  `temperature`/`humidity`). Breaking change for any existing DHT
  subscriber expecting the old combined payload/topic.
- `RuntimeService._poll_publish_adapters()` (`app/services/runtime.py`) now
  skips publishing a `PotentiometerAdapter`/`RotaryAngleAdapter` reading
  unless it has moved by at least `CHANGE_THRESHOLD_PERCENT` (1.0) from the
  last one published, instead of republishing the same percentage every poll
  tick regardless of whether the dial moved. A tolerance rather than exact
  equality, since ESP32 ADC noise jitters `read_u16()` by tens of raw counts
  even with the wiper stationary - enough to flip the rounded-to-1-decimal
  percent on every read. Other publish adapters (DHT22/DHT11, etc.) are
  unaffected and continue to publish every tick as before.
- `tinker.py provision` no longer pushes `device_config.json` to a device
  over serial (and no longer takes `--port`/`--baud`) - it now only writes
  `device_config.json` (and, via the Agnes API, `./certs/`) on the host.
  Provisioning and deploying were doing the same upload with a second,
  provision-specific raw-REPL failure mode for no benefit; run `build` then
  `deploy` (or `watch`) to push the result to a device, same as any other
  code change.
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
- `tinker.py topics` is replaced by a `tinker.py topic` command group
  (`topic list`, `topic tree`) - `topic list` now renders one unified
  PUB/SUB/STATUS table (Direction, Topic, Device, Component, Purpose, QoS)
  instead of three separate tables, with `--pub`/`--sub`/`--device`/
  `--component`/`--purpose` filters; `topic tree` renders the same topic
  set as a hierarchical tree grouped by path segment, matching `device
  tree`'s rendering style. No backward-compatible `topics` alias.
- Unified MQTT contract: every device now publishes/subscribes on exactly
  four fixed topics derived straight from `mqtt_username` -
  `devices/{mqtt_username}/data` (merged multi-key telemetry publish),
  `.../command` (multi-key JSON command routing by adapter name, see
  `RuntimeService._handle_command_message()`), `.../state` (periodic +
  post-command full-state report, `state_report_interval_seconds`, default
  `60`), and `.../availability` (birth/LWT) - replacing per-adapter topic
  composition from `mqtt_topic_pub`/`mqtt_topic_sub`/`mqtt_topic_status`
  plus each adapter's own `*_topic_suffix`. `main.py`'s `_topic()` composer
  is removed; adapter names now double as JSON keys instead of being
  composed into standalone topic strings. `*_topic_suffix` config keys are
  still read, but repurposed as JSON key names in the merged payloads
  rather than topic path segments. `StatusLEDAdapter.state()` added so LED
  participates in the state report the same way relay/RGB do.
  `RegistrationService` now also saves the registration response's
  `lwt_topic`/`lwt_payload` into `device_config.json`'s
  `mqtt_lwt_topic`/`mqtt_lwt_message`. Breaking change for any existing
  subscriber on the old per-adapter topic layout - see `docs/mqtt.md` for
  the full contract.

### Fixed
- `boot.py` now claims the `network.WLAN(network.STA_IF)` singleton as its
  first action, before `import _boot` pulls in the rest of the app's module
  tree. On the ESP32 port, `network.WLAN(id)` only runs the heap-heavy
  `esp_wifi_init()` rx/tx buffer allocation on its first call per interface;
  doing that call after the full service import graph had already eaten the
  heap could fail with `OSError: WiFi Out of Memory` (esp-idf's "Expected to
  init 10 rx buffer, actual is 2"). `RuntimeService.__init__`
  (`app/services/runtime.py`) also now constructs `WiFiService` before the
  heavier `LogService`/`CrashLogService`/`MetricsService`/`ErrorHandlerService`
  objects, with an explicit `gc.collect()` first.
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
- `tinker.py device logs`/`device monitor`/`device repl` no longer dump
  mpremote's raw Python traceback when the board is unplugged, hard-reset,
  or the port renumbers while the session is closing - mpremote's
  `do_disconnect()` toggles the RTS/DTR lines on close, which raises an
  unhandled `OSError` once the serial node is already gone. The tailed
  output was already delivered by then, so this now prints a short "safe to
  ignore" note instead.

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
