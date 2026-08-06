# Security Policy

## Supported Versions

Microweaver does not yet publish tagged releases. Security fixes are applied
to the `main` branch only.

| Version | Supported          |
| ------- | ------------------- |
| main    | :white_check_mark:  |

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

Microweaver runs on-device (ESP32/MicroPython) and talks to WiFi and MQTT
infrastructure. Reports involving credential handling in
`device_config.json`, MQTT/WiFi reconnect logic, or the watchdog/boot-loop
protection services are especially relevant.
