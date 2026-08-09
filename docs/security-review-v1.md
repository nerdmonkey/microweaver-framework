# v1.0 Security Review

This document records the security review requested in [issue #175](https://github.com/nerdmonkey/microweaver-framework/issues/175). It is both the review record and the release checklist: **v1.0 must not be tagged while any item in [Release gates](#release-gates) is unchecked.**

## Review record

- Date: 2026-08-09
- Reviewed revision: `bf9b41e` (`origin/main`)
- Static analysis: `tox -e lint` passed (Flake8 and Bandit, no findings)
- Manual scope: MQTT TLS and credentials, OTA manifest/download/apply, SoftAP provisioning, configuration storage, and release controls

The review establishes what the host-side code and tests currently prove. It
does not substitute for TLS, OTA, and provisioning checks on the baseline ESP32
firmware and real network services.

## Threat boundary

Microweaver assumes that the device owner controls the physical device, serial
port, MQTT broker/ACLs, OTA origin, and build artifacts. An attacker may be on a
shared WiFi network, within radio range during provisioning, able to publish to
an incorrectly scoped MQTT topic, or able to interfere with an unprotected OTA
connection. Physical access or raw-REPL access is treated as full device
compromise; Microweaver does not provide encrypted storage or a hardware-backed
secret store.

`device_config.json`, local `dist/` output, and backups can contain credentials
or private keys. They must be handled as secrets even though
`device_config.json` and generated directories are gitignored.

## Findings and mitigations

### MQTT transport and authorization

The runtime supports username/password authentication and optional TLS, with
optional client certificate/key parameters. TLS defaults to disabled, and the
framework does not currently expose a CA trust anchor, server hostname, or a
"verification required" policy. Host unit tests confirm argument wiring only;
they do not prove certificate or hostname validation on MicroPython. The
boot-loop safe-mode connection also omits the configured TLS and client
certificate/key settings, so its recovery OTA channel can fall back to
plaintext even when the normal runtime is configured for TLS.

Risk: without an authenticated TLS session, credentials, telemetry, commands,
and OTA triggers can be observed or altered. A shared or broad broker ACL also
lets one compromised client command other devices.

Required mitigation for a production deployment:

- Use TLS, per-device credentials, and least-privilege publish/subscribe ACLs.
- Reject plaintext credential use in the deployment profile.
- Preserve the deployment's TLS policy and credentials in safe mode; do not
  weaken transport security during recovery.
- Verify the broker certificate and hostname on the exact MicroPython firmware
  and baseline board; client certificates alone do not authenticate the server.
- Give each device a unique command and OTA trigger topic.

### OTA authenticity, replay, and availability

`OtaService` requires a SHA-256 for every payload, verifies the downloaded
bytes, stages all files before swapping, and keeps backups for rollback. These
controls reject corruption and a payload that differs from its manifest.

Risk: the manifest is not signed. A party able to replace both the manifest and
payload can provide a matching checksum and execute arbitrary device code. HTTP
URLs are accepted, and HTTPS authenticity depends on the TLS behavior of the
deployed MicroPython firmware. Version comparison checks only inequality, so an
older release can be replayed. Manifest-controlled paths and unbounded payloads
also make a trusted OTA origin equivalent to privileged device access and allow
storage exhaustion.

Required mitigation for a production deployment:

- Serve manifests and payloads only over authenticated HTTPS and verify that
  certificate/hostname failures are rejected on the real board.
- Add a device-verifiable signed-manifest trust root before treating a CDN or
  transport checksum as an authenticity boundary.
- Reject downgrade/replay attempts and constrain manifest size, file count,
  paths, and payload sizes.
- Restrict the MQTT OTA trigger topic and protect the OTA publishing account.
- Exercise apply, failed-checksum cleanup, reboot, confirmation, and rollback
  using a real CDN and board before release.

### SoftAP provisioning

Provisioning starts an open AP by default and accepts WiFi credentials and an
optional claim code over plaintext HTTP. A configured AP password enables WPA/
WPA2, but the server remains unauthenticated HTTP. The AP stays active after a
successful submission until provisioning is interrupted or the device reboots.
Scanned SSIDs are inserted into the HTML form without escaping. When device
claiming is enabled, the registration service also submits the claim code to an
arbitrary configured URL and stores the returned device certificate and private
key without enforcing authenticated HTTPS.

Risk: a nearby party can observe or replace submitted credentials on the
default open AP, resubmit configuration while the portal remains available, or
inject markup through a crafted SSID.

Required mitigation for a production deployment:

- Use a unique, non-default per-device AP password delivered out of band.
- Keep the provisioning window short, require physical possession/presence,
  and stop or reboot after a successful connection.
- Escape scanned SSIDs before rendering them and add request/body size limits.
- Treat claim codes as short-lived, one-time secrets and invalidate them after
  use.
- Require authenticated HTTPS for claim registration and verify rejection of
  invalid certificates and hostnames on the baseline firmware.
- Verify the complete flow against a real phone/laptop and board, including
  unauthorized-client and resubmission attempts.

### Credential storage and operational handling

Credentials and device keys are stored in plaintext because the baseline ESP32
storage layer has no framework-managed encryption. Provisioning prompt tests
confirm that existing password values are not echoed as defaults, and runtime
logs do not intentionally print submitted passwords.

Required mitigation for a production deployment:

- Use unique, revocable device credentials with minimal permissions.
- Protect `device_config.json`, build output, backups, serial access, and CI
  artifacts; never commit or attach them to issues or pull requests.
- Avoid passing credentials as command-line flags where shell history or process
  listings can expose them; prefer the hidden interactive prompts or another
  protected input channel.
- Rotate credentials after suspected physical, serial, build-host, or backup
  exposure.
- Prefer hardware-backed or encrypted secret storage when the target platform
  provides a verified implementation.

## Release gates

Review activities completed by this change:

- [x] Run `tox -e lint` (Flake8 and Bandit).
- [x] Review MQTT credential and TLS wiring.
- [x] Review OTA manifest, checksum, staging, and rollback paths.
- [x] Review SoftAP credential and claim-code handling.
- [x] Document the threat boundary, findings, and required mitigations.

Production gates still required before tagging v1.0:

- [ ] Decide and implement the MQTT server-authentication policy, then record a
  successful broker handshake and rejected invalid-certificate/hostname tests
  on the baseline board and firmware.
- [ ] Ensure safe mode preserves the configured MQTT TLS policy and credentials.
- [ ] Add OTA manifest authenticity and replay/downgrade protection.
- [ ] Complete a real CDN-to-board OTA apply, confirmation, failed-update, and
  rollback cycle.
- [ ] Harden SoftAP defaults/lifetime and HTML rendering, then complete an
  interception/resubmission-oriented provisioning test on a real board.
- [ ] Require authenticated HTTPS for device claim registration and verify it on
  the baseline board and firmware.
- [ ] Confirm per-device broker ACLs, OTA publishing permissions, credential
  rotation, and artifact/backup handling for the deployment environment.
- [ ] Re-run `tox -e lint`, the full pytest suite, and a secret scan on the exact
  v1.0 release commit.

The release decision is therefore **not approved yet**. Static analysis and the
manual code review are complete, but the unchecked design and hardware gates
remain blockers rather than risks silently accepted by this review.
