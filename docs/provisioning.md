# First-Boot Provisioning Guide

How a blank device gets WiFi credentials, registers with a backend, and how to send it back through the whole flow again: the [SoftAP captive-portal flow](#softap-captive-portal-flow), the [bench/serial alternative](#bench-alternative-tinkerpy-provision), [backend claim registration](#backend-claim-registration), and [factory reset](#factory-reset).

- [Overview](#overview)
- [SoftAP captive-portal flow](#softap-captive-portal-flow)
- [Bench alternative: tinker.py provision](#bench-alternative-tinkerpy-provision)
- [Backend claim registration](#backend-claim-registration)
- [Factory reset](#factory-reset)
- [Configuration reference](#configuration-reference)

## Overview

A device with no `wifi_ssid` configured can't reach `main.start()` at all, so `_boot.py` diverts it before the normal application ever runs:

```
_boot.run_bootstrap()
    |
    +-- no WIFI_SSID configured --> main.start_provisioning() --> ProvisioningService.run()
    |                                   (SoftAP + HTTP form, saves wifi_ssid/wifi_password/claim_code)
    |
    +-- WiFi configured, CLAIM_ENABLED and DEVICE_ID empty and CLAIM_CODE set
    |                              --> main.start_claim() --> RegistrationService.register()
    |                                   (WiFi connect, then POST claim_code to backend)
    |
    +-- otherwise -----------------> main.start() --> PublishService/SubscribeService.run()
```

There are two independent ways to get WiFi credentials onto the device — the [SoftAP flow](#softap-captive-portal-flow) (no laptop/serial connection needed, phone joins the device's own AP) and the [bench flow](#bench-alternative-tinkerpy-provision) (`tinker.py provision`, headless, over the same serial cable used for `deploy`). Both end up writing the same `device_config.json` keys, so either can be used interchangeably depending on whether the device is reachable over WiFi or only over USB.

Backend claim registration and factory reset are separate concerns that sit either side of provisioning: claim registration runs *after* WiFi is up but before normal operation, and factory reset is what sends a claimed, WiFi-configured device back to square one.

## SoftAP captive-portal flow

`ProvisioningService` (`app/services/provisioning.py`) is what `main.start_provisioning()` (`main.py`) constructs and runs when `_boot.py` finds no `WIFI_SSID`:

```python
class ProvisioningService:
    def __init__(
        self,
        ap_ssid="Microweaver-Setup",
        ap_password="",
        ap_ip="192.168.4.1",
        port=80,
        setting=None,
        led=None,
        wifi_test_timeout_seconds=WIFI_TEST_TIMEOUT_SECONDS,
    ): ...
    def run(self):   # starts the AP + HTTP server, loops handling requests forever
```

1. `start()` brings up `network.WLAN(network.AP_IF)` as an open (or WPA2, if `ap_password` is set) access point at `ap_ssid`/`ap_ip`, and turns the status LED solid on if one is configured — signaling "AP active, waiting for a client."
2. `run()` binds a plain socket HTTP server on `port` (default `80`) and loops `accept()`ing connections with a 1s timeout, so a Ctrl-C/raw-REPL interrupt still gets a chance to land between clients instead of blocking forever.
3. A client (phone or laptop joining `Microweaver-Setup`) requesting anything other than `POST /save` gets back `_render_form()` — an HTML page with a `<select>` populated from `scan_networks()` (a live WiFi scan over `network.WLAN(network.STA_IF)`), plus password and optional claim-code fields.
4. `POST /save` goes through `_handle_request()` → `_save_credentials()`:
   - Validates `ssid` is non-empty (raises `ValueError` → HTTP 400 otherwise).
   - Persists `wifi_ssid`, `wifi_password`, and `claim_code` (if given) via `setting.save(...)`.
   - Calls `_test_wifi_connection()` — activates the station interface and waits up to `wifi_test_timeout_seconds` (default 20s) for `isconnected()`, so the response can tell the user whether the credentials actually work rather than just that they were saved.
   - Blinks the status LED: 2 slow blinks on a successful test connection, 5 fast blinks on failure — the only feedback available on a device with no display.
5. The client sees "Credentials saved. Connected!" or a failure message telling them to check the password and retry; the AP and HTTP server keep running either way; provisioning doesn't exit itself. It runs until the finally block hits `stop()`, which only happens if `run()` raises or is interrupted — restarting/rebooting the device is what actually applies the new credentials and moves on to the WiFi-configured branch in `_boot.py`.

`_parse_form`/`_unquote` implement URL-decoding for the `application/x-www-form-urlencoded` body by hand — there's no `urllib` in this MicroPython build, so this is the framework's own minimal decoder rather than a stdlib call.

## Bench alternative: tinker.py provision

`tinker.py provision` (repo root, host-side CLI) is the headless equivalent of the SoftAP flow for benches where the device is easier to reach over USB than to have a phone join its AP:

```shell
python tinker.py provision --port <port>
```

- Prompts interactively (`typer.prompt`) for any of `wifi_ssid`, `wifi_password`, `mqtt_broker`, `mqtt_port`, `mqtt_client_id`, `mqtt_topic_pub`, `mqtt_topic_sub`, `mqtt_username`, `mqtt_password` not already given as CLI flags, seeding defaults from the device's existing `device_config.json` (falling back to `device_config.json.example`) so re-running it doesn't wipe unrelated settings.
- Secret fields (`wifi_password`, `mqtt_password`) never echo an existing value as the prompt's own `[default]` hint — the prompt shows `[unchanged]` instead, and leaving it blank keeps the existing secret. Typing a new value replaces it.
- Requires a TTY for any field left unanswered on the command line (`_require_tty_for_missing`) — a fully-flagged, non-interactive invocation (e.g. from a provisioning script) is supported by passing every field as a flag.
- Writes the merged settings to a local `device_config.json`, then pushes that file to the device over the same raw-REPL serial connection `deploy`/`backup` use (`_raw_repl_session`, `DeviceTransport.put_file`) — no `mpremote` required.

Unlike the SoftAP flow, this path does not run a live WiFi test on-device — it only writes the config file. The device applies it (and can be watched connecting) on its next boot.

## Backend claim registration

`RegistrationService` (`app/services/registration.py`) is what `main.start_claim()` runs once WiFi is up, if `_boot.py` finds `CLAIM_ENABLED` true, `DEVICE_ID` still empty, and `CLAIM_CODE` set (from provisioning, above):

```python
class RegistrationService:
    def __init__(self, claim_url="", claim_code="", setting=None): ...
    def is_claimed(self):   # bool(setting and setting.DEVICE_ID)
    def register(self):     # POST {"claim_code": ...} to claim_url
```

`register()` posts the claim code to `claim_url` via `urequests`, and on a `200` response with a `device_id` in the body, persists `device_id`, `device_cert`, `device_key` and clears `claim_code` via `setting.save(...)` — clearing the claim code prevents `_boot.py` from re-triggering registration on the next boot once `DEVICE_ID` is set. Any failure (network error, non-200, missing `device_id`) prints a message and returns `None` without raising — a claim failure is not fatal to boot, it just means the device stays unclaimed and `main.start_claim()` will be attempted again on the next boot that still sees `CLAIM_CODE` set and `DEVICE_ID` empty.

`is_claimed()` is a plain predicate other code can use to check claim status; `_boot.py` itself checks the same condition inline (`CLAIM_ENABLED and not DEVICE_ID and CLAIM_CODE`) rather than calling it, since it needs to decide whether to call `start_claim()` at all before a `RegistrationService` exists yet.

## Factory reset

`FactoryResetService` (`app/services/factory_reset.py`) is what sends a provisioned, possibly-claimed device back through the whole flow above. `_boot.py` constructs and checks it — before `import main` — whenever `FACTORY_RESET_ENABLED` is true:

```python
class FactoryResetService:
    def __init__(self, pin=-1, hold_seconds=3, sentinel_path="reprovision.flag", setting=None): ...
    def should_trigger(self):    # sentinel file present, or button held long enough
    def clear_credentials(self): # wipes wifi/mqtt/claim/device_id/cert/key via setting.save
```

`should_trigger()` returns `True` from either of two independent signals:

1. **Sentinel file** — `sentinel_path` (default `reprovision.flag`) exists on the device's filesystem. Anything that can write a file to the device (`tinker.py`, an OTA update, application code reacting to some other condition) can request a reset this way without needing a physical button.
2. **Button held** — `pin` is a valid GPIO (`>= 0`) wired active-low with a pull-up, and it reads held low for the full `hold_seconds` (default 3s) at boot. `pin=-1` (the default) disables the button check entirely.

When either fires, `_boot.py` calls `clear_credentials()`, which wipes `wifi_ssid`, `wifi_password`, `mqtt_username`, `mqtt_password`, `claim_code`, `device_id`, `device_cert`, and `device_key` back to empty strings and removes the sentinel file if present. With `wifi_ssid` now empty, the *same* boot's later `if not setting.WIFI_SSID` check in `_boot.py` routes straight into `main.start_provisioning()` — a factory reset and a blank first boot land in the exact same place, the [SoftAP flow](#softap-captive-portal-flow) above.

`clear_credentials()` only clears state; it does not itself reboot or reconfigure anything else — boot-loop counters, crash logs, and OTA state are untouched, since a factory reset is about re-provisioning network/backend identity, not the device's reliability history.

## Configuration reference

All keys live in `device_config.json` (see `device_config.json.example`); every one has a safe default and none are required for the device to boot.

| Key | Default | Purpose |
|---|---|---|
| `wifi_ssid` | `""` | Empty triggers provisioning mode on boot |
| `provisioning_ap_ssid` | `Microweaver-Setup` | SoftAP network name during provisioning |
| `provisioning_ap_password` | `""` | Empty = open AP; set for WPA2 |
| `provisioning_ap_ip` | `192.168.4.1` | SoftAP's own IP / captive portal address |
| `provisioning_port` | `80` | HTTP server port for the setup form |
| `provisioning_led_enabled` | `false` | Drives a status LED during provisioning |
| `provisioning_led_pin` | `2` | GPIO for the provisioning status LED |
| `claim_enabled` | `false` | Enables backend claim registration after WiFi connects |
| `claim_url` | `""` | Backend endpoint `RegistrationService` POSTs the claim code to |
| `claim_code` | `""` | Set via provisioning form or `tinker.py provision`; cleared on successful claim |
| `device_id` | `""` | Set by a successful claim; presence means the device is claimed |
| `device_cert` | `""` | Set by a successful claim |
| `device_key` | `""` | Set by a successful claim |
| `factory_reset_enabled` | `false` | Enables `FactoryResetService` checks at boot |
| `factory_reset_pin` | `-1` | GPIO for the reset button; `-1` disables the button check |
| `factory_reset_hold_seconds` | `3` | How long the button must be held to confirm a reset |
| `factory_reset_sentinel_path` | `reprovision.flag` | File whose presence also triggers a reset |
