# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
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

## [0.1.0] - 2026-08-08

### Added
- Initial release of the Microweaver framework: WiFi/MQTT/watchdog services,
  OTA update service, safe-mode remote recovery, and the `tinker.py` CLI.

[Unreleased]: https://github.com/nerdmonkey/microweaver-framework/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/nerdmonkey/microweaver-framework/releases/tag/v0.1.0
