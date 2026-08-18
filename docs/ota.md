# OTA Update Guide

How a deployed device pulls and applies a firmware update over the air: the [manifest-driven download/apply flow](#update-flow), the [MQTT trigger](#mqtt-trigger), [rollback via boot-loop protection](#rollback-via-boot-loop-protection), [safe mode's recovery path](#ota-in-safe-mode), and how [`tinker.py fleet push`](#tinkerpy-fleet-push-vs-ota) fits alongside it.

- [Overview](#overview)
- [Update flow](#update-flow)
- [MQTT trigger](#mqtt-trigger)
- [Status reporting](#status-reporting)
- [Rollback via boot-loop protection](#rollback-via-boot-loop-protection)
- [OTA in safe mode](#ota-in-safe-mode)
- [`tinker.py fleet push` vs OTA](#tinkerpy-fleet-push-vs-ota)
- [Manifest format](#manifest-format)
- [Configuration reference](#configuration-reference)

## Overview

`OtaService` (`app/services/ota.py`) is a plain class that knows how to fetch a JSON manifest over HTTP, download and checksum each listed file, stage it, and swap it into place with a backup kept for rollback. It has no opinion on *when* it runs — that's wired in by whichever run loop constructs it:

```
MQTT message on ota_topic
    |
    +-- PublishService/SubscribeService._handle_ota_message --> OtaService.apply_update()
                                                                       |
                                                                       +-- success --> reboot expected --> next boot confirms
                                                                       +-- failure --> files left untouched, staged copies cleaned up
```

The same `OtaService` is also constructed by `SafeModeService` (`app/services/safe_mode.py`) so a boot-looping device can still receive a recovery update — see [OTA in safe mode](#ota-in-safe-mode).

`ota_enabled` defaults to `false`; nothing OTA-related runs until it's turned on in `device_config.json`.

## Update flow

`apply_update()` (`app/services/ota.py:100-152`) drives the whole sequence:

1. **`check_for_update()`** (`ota.py:37-54`) — `GET`s `ota_manifest_url` and parses the JSON body. A missing URL, unreachable host, or non-200 response just skips the check (prints and returns `None`) — never raises into the caller.
2. **`is_update_available()`** (`ota.py:56-61`) — compares `manifest["version"]` against `setting.APP_VERSION`; no manifest, no `version` key, or a matching version means no update.
3. **Stage** — for each entry in `manifest["files"]`, `download_file()` (`ota.py:77-98`) fetches the file to `<path>.ota_new` and verifies its SHA-256 against the manifest's `sha256` before accepting it. A file with no `sha256` in its manifest entry aborts the whole update (`ota.py:112-118`) — OTA never applies an unverified file. Any download or checksum failure aborts and cleans up every already-staged file (`_remove_all`, `ota.py:114,123,226-228`), so a partial update never applies.
4. **Swap** — once every file is staged, each live file (if it exists) is renamed to `<path>.ota_bak` and the staged copy is renamed into its place (`ota.py:130-137`). This is a rename-based swap, not a copy, so it's fast and doesn't require double the free space for the swap step itself (staging still needs room for the downloaded copies).
5. **Persist state** — `_write_state()` (`ota.py:139-145, 250-255`) writes `{"version", "previous_version", "files": {path: had_backup}}` to `ota_state.json` (path configurable via `ota_state_path`). This is the record `rollback()` and `confirm_update()` read later, and it survives the reboot that normally follows an update.
6. `setting.save(app_version=...)` persists the new version into `device_config.json` so `APP_VERSION` reflects the update even before the next boot re-reads config.

`apply_update()` does not reboot the device itself — the caller (an MQTT handler, or `SafeModeService`) decides whether/when to call `machine.reset()`. In the main run loop's `_handle_ota_message`, no explicit reset is issued, since applying new files takes effect on the *next* boot; in safe mode, `_on_message` (`app/services/safe_mode.py:71-78`) calls `machine.reset()` immediately after a successful apply.

## MQTT trigger

`SubscribeService` subscribes to `ota_topic` (default `ota/update`) only when both `ota_enabled` and the topic are set (`app/services/subscribe.py:92-94`). Any message published to that topic — the payload content isn't parsed, it's just a trigger — invokes:

```python
def _handle_ota_message(self, topic, message):
    print("OTA update triggered via MQTT:", message.decode())
    self.error_handler.guard(self.ota_service.apply_update, "ota_update")
```

(`app/services/subscribe.py:171-173`). `error_handler.guard` means an unexpected exception inside `apply_update()` is caught, logged, and recorded as a metric rather than crashing the run loop — a bad manifest or network blip during OTA doesn't take down the device's normal MQTT/publish behavior.

To trigger an update from the host side, publish any payload to the configured topic, e.g.:

```shell
mosquitto_pub -h <broker> -t ota/update -m "check"
```

`PublishService` builds and confirms/reports on the same `OtaService`, but never subscribes to any topic (it's publish-only) — it can't itself receive an OTA trigger. An `OTA_ENABLED` device running only `PublishService` still gets `confirm_update()` called after a successful connect and status published to `ota_status_topic`, but `apply_update()` is never called on the main-loop path unless something else (a `SubscribeService`/`RuntimeService` process, or [safe mode](#ota-in-safe-mode)) triggers it.

## Status reporting

If `on_status` is wired (both `PublishService` and `SubscribeService` pass `self._report_ota_status`), `OtaService` publishes a JSON payload to `ota_status_topic` (default `ota/status`) at each stage transition: `downloading`, `applied` or `failed` (from `apply_update()`), `rolled_back` (from `rollback()`), and `confirmed` (from `confirm_update()`). Each payload always carries `status` and `app_version`; `applied`/`failed`/`rolled_back` also carry `version`, and `failed` carries `error` (`ota.py:188-201`, `subscribe.py:188-190`). A status-reporting failure (e.g. not connected to MQTT) is caught and printed, never raised.

## Rollback via boot-loop protection

OTA rollback is manual (`rollback()`, `ota.py:154-173`) — nothing calls it automatically. What *is* automatic is the interaction with [boot-loop protection](reliability.md#boot-loop-protection): if a bad update leaves the device unable to reach a healthy state (crashes before `BootLoopGuard.confirm()` runs), the device keeps rebooting, the boot-loop counter climbs, and once it exceeds `boot_loop_max_attempts` the device lands in safe mode instead of crash-looping forever. From there, [safe mode's OTA listener](#ota-in-safe-mode) is the intended way to push a fixed build — not an automatic rollback of the bad one.

To roll back explicitly instead (restore the previous version from the backups OTA already kept):

```shell
mpremote connect <port> exec "from app.services.ota import OtaService; from config.app import Setting; s = Setting().get_settings(); OtaService(setting=s, state_path=s.OTA_STATE_PATH).rollback()"
```

`rollback()` reads `ota_state.json`, removes each currently-live file and restores its `.ota_bak` copy where one exists, restores `APP_VERSION` to `previous_version` via `setting.save()`, then clears the state file (`ota.py:154-173`). It only has something to roll back to if the *last* `apply_update()` succeeded far enough to reach the swap step — a failed download/checksum stage never touches live files in the first place, so there's nothing to undo.

`confirm_update()` (`ota.py:175-186`) is the counterpart: called once per successful boot by `PublishService.run()`/`SubscribeService.run()` right after connecting (`subscribe.py:254-255`), it deletes the `.ota_bak` backups and clears `ota_state.json` — the update is considered good and rollback is no longer possible for it. This mirrors `BootLoopGuard.confirm()`, which runs at the same point in the loop: both treat "reached a healthy connected state" as proof the boot succeeded.

## OTA in safe mode

`SafeModeService` only builds its WiFi/MQTT/OTA stack when `wifi_ssid`, `mqtt_enabled`, and `ota_enabled` are all set (`app/services/safe_mode.py:21-44`) — a device with none of those configured just idles (`_sleep_forever`). When it can run recovery, `_run_recovery_loop()` connects to MQTT, subscribes to the same `ota_topic`, and waits (`safe_mode.py:56-69`). Unlike the main run loop, safe mode's handler reboots immediately on a successful apply:

```python
def _on_message(self, topic, message):
    print("SAFE MODE: OTA update triggered:", message.decode())
    try:
        if self.ota_service.apply_update():
            print("SAFE MODE: update applied, restarting")
            machine.reset()
    except Exception as e:
        print("SAFE MODE: OTA update failed:", e)
```

(`safe_mode.py:71-78`). This is the primary recovery path for a boot-looping device: push a fixed manifest to `ota_topic`, safe mode applies it and resets, and the next boot either reaches a healthy state (clearing the boot-loop counter) or loops back into safe mode again if the fix didn't work. See [Recovery procedures](reliability.md#recovery-procedures) for the full diagnostic flow around this.

## `tinker.py fleet push` vs OTA

These are two independent deployment paths, not layers of the same one:

| | OTA (`ota/update` MQTT trigger) | `tinker.py fleet push` |
|---|---|---|
| Transport | Device-initiated HTTP `GET` against `ota_manifest_url` | Host-initiated, over serial (`mpremote fs cp`) |
| Trigger | MQTT message on `ota_topic` | Manual CLI invocation |
| Scope | One device, reacts to its own subscription | Every `--port` given (or every detected port) in one invocation |
| Verification | Per-file SHA-256 against the manifest | None — raw file copy |
| Rollback | `.ota_bak` backups + `rollback()` | None — files are overwritten directly |
| Needs device on WiFi/MQTT | Yes | No — serial only |

`fleet push` (see [`docs/tinker.md#fleet-push`](tinker.md#fleet-push)) uploads a local build (default `./dist`) to every listed device over `mpremote fs cp -r`, optionally hard-resetting each one first with `--reset`. It has no concept of manifests, checksums, or versions — it's the bench/lab equivalent of plugging in every board and copying files by hand, useful when devices are physically reachable and you don't want to stand up a manifest host. OTA is the field equivalent: no serial access needed, but it requires `ota_manifest_url` to be serving a valid manifest and the referenced files, and depends on the device having a working WiFi/MQTT path in the first place — which is exactly the path a *boot-looping* device may not have, hence [safe mode's](#ota-in-safe-mode) narrower fallback subscription being separate from the main run loop's.

## Manifest format

`check_for_update()` expects `ota_manifest_url` to return JSON shaped like:

```json
{
  "version": "1.4.0",
  "files": {
    "app/services/foo.py": {
      "url": "https://example.com/builds/1.4.0/foo.py",
      "sha256": "3f9b2c..."
    },
    "main.py": "https://example.com/builds/1.4.0/main.py"
  }
}
```

Each entry in `files` is either an object with `url`/`sha256`, or a bare URL string (`_file_url_and_checksum`, `ota.py:203-206`). A bare-string entry has no checksum, and `apply_update()` treats a missing checksum as an aborting error (`ota.py:112-118`) — in practice every entry needs the object form with `sha256` for an update to actually apply. Paths are relative to the device filesystem root and are written/renamed in place, so a manifest can update any file the device has permission to write, not just application code.

## Configuration reference

All keys live in `device_config.json` (see `device_config.json.example`); OTA is fully inert until `ota_enabled` is `true`.

| Key | Default | Purpose |
|---|---|---|
| `ota_enabled` | `false` | Enables `OtaService` construction and the `ota_topic` MQTT subscription, in both the main run loop and safe mode |
| `ota_manifest_url` | `""` | HTTP(S) URL returning the manifest described [above](#manifest-format); empty skips every check |
| `ota_state_path` | `ota_state.json` | Path to the persisted apply/rollback state file |
| `ota_topic` | `ota/update` | MQTT topic that triggers `apply_update()`; any published payload triggers it, content is ignored |
| `ota_status_topic` | `ota/status` | MQTT topic status payloads (`downloading`/`applied`/`failed`/`rolled_back`/`confirmed`) are published to |

Related: [boot-loop protection](reliability.md#boot-loop-protection) and [safe mode](reliability.md#safe-mode) in the reliability guide, `boot_loop_*` and `safe_mode_sleep_seconds` keys there.
