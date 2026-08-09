# Security Policy

## Supported Versions

Microweaver's pre-1.0 tags are development snapshots and do not receive
security backports. Security fixes are applied to the `main` branch only until
the project publishes its support policy for stable releases.

| Version          | Supported          |
| ---------------- | ------------------ |
| main             | :white_check_mark: |
| pre-1.0 snapshots | :x:               |

## Reporting a Vulnerability

Please **do not** open a public GitHub issue for security vulnerabilities.

Instead, report it privately by emailing **sydel.palinlin@gmail.com** with:

- A description of the vulnerability and its potential impact
- Steps to reproduce, including any relevant firmware/device configuration
- Affected file(s) or service(s), if known

You should receive an acknowledgement within a few days. Once a fix is
confirmed, a patch will be merged to `main` and, where appropriate, the
reporter credited in the release notes.

## Scope

Microweaver runs on-device (ESP32/MicroPython) and talks to WiFi, MQTT, and OTA
infrastructure. Reports involving these areas are especially relevant:

- Credential and device-key handling in `device_config.json`
- MQTT authentication, authorization, and TLS
- OTA manifest or payload authenticity, integrity, replay, and rollback
- SoftAP provisioning and claim-code handling
- Serial/physical access assumptions and recovery services

The tracked security review and release gates for v1.0 are documented in
[`docs/security-review-v1.md`](docs/security-review-v1.md).
