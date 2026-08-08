# `tinker.py` CLI Reference

`tinker.py` builds, uploads, downloads, and manages firmware for ESP32 (and other MicroPython-supported) devices. It is a [Typer](https://typer.tiangolo.com/) CLI built on top of [`esptool`](https://github.com/espressif/esptool) (chip-level access) and [`mpremote`](https://github.com/micropython/micropython/tree/master/tools/mpremote) (filesystem/REPL access over serial).

- [Prerequisites](#prerequisites)
- [Global concepts](#global-concepts)
  - [Shell completion](#shell-completion)
  - [Config resolution order](#config-resolution-order)
  - [The `.microweaver` config file](#the-microweaver-config-file)
  - [Port auto-detection](#port-auto-detection)
- [Command reference](#command-reference)
  - [`build`](#build)
  - [`upload`](#upload)
  - [`download`](#download)
  - [`watch`](#watch)
  - [`port`](#port)
  - [`config show`](#config-show)
  - [`config set`](#config-set)
  - [`device reset`](#device-reset)
  - [`device info`](#device-info)
  - [`device ls`](#device-ls)
  - [`device tree`](#device-tree)
  - [`device test-adapter`](#device-test-adapter)
- [Common workflows](#common-workflows)
- [Troubleshooting](#troubleshooting)

## Prerequisites

| Tool | Required for | Install |
|---|---|---|
| `mpy-cross-multi` | `build` | bundled with the project's build deps |
| `mpremote` | `download`, `provision`, `watch`, `fleet push`, `device repl`, `device logs`/`monitor` | `pip install mpremote` |
| `esptool` (Python API) | `device reset`, `device info` (chip read) | installed as a project dependency, no separate CLI install needed |

The commands above check for `mpremote` on `PATH` up front and print an install hint if it's missing, rather than failing with a raw `FileNotFoundError`. `upload`, `device ls`, `device tree`, `device info` (firmware read), `device health`, `device rm`, `device mkdir`, and `device test-adapter` talk to the device directly over a raw-REPL serial connection ([`DeviceTransport`](../device_transport.py)) and do not require `mpremote` on `PATH`.

## Global concepts

### Shell completion

`tinker.py` is a [Typer](https://typer.tiangolo.com/) CLI, so it ships tab-completion for commands and options (e.g. `--port`, `--baud`, subcommand names) via [`click`](https://click.palletsprojects.com/)/`shellingham`. Install it once per shell:

```shell
python tinker.py --install-completion
```

Restart your shell (or source its rc file) afterward. To preview the completion script without installing it, use `--show-completion`.

### Config resolution order

Every command that needs a `--port` or `--baud` resolves them in this order:

1. Explicit CLI flag (`--port`/`-p`, `--baud`/`-b`)
2. Saved default in `.microweaver` (see below)
3. Interactive prompt — `tinker.py` scans available serial ports and either auto-selects the only one found, or lists them and asks you to pick

If stdin isn't a TTY (e.g. running in CI) and no port is resolvable, the command exits with code `1` and points you at `tinker.py port` or `tinker.py config set --port <port>`.

> **Note:** `mpremote`'s CLI hardcodes 115200 baud — there is no override flag upstream as of 1.28.0. `--baud` is accepted by `tinker.py` for interface parity and gets saved to `.microweaver`, but it has no effect on the actual transfer. `tinker.py` prints a `NOTE:` to stderr whenever a non-default baud is requested, so this isn't silent.

### The `.microweaver` config file

An INI file at the project root, written by `config set` and updated automatically by `upload`/`download` after a successful run:

```ini
[default]
port = /dev/tty.usbserial-0001
baud = 115200
path = dist
```

View it any time with `tinker.py config show`; delete it (or edit it directly) to clear saved defaults.

### Port auto-detection

`tinker.py port` lists everything `pyserial` can see. When a command needs a port and none is configured:

- **Exactly one port found** → used automatically, printed to stdout.
- **Multiple ports found** → numbered table printed, you're prompted to pick one.
- **No ports found** → error, exit code `1`.

## Command reference

### `build`

Compile `app/`, `config/`, `_boot.py`, and `main.py` to `.mpy` bytecode into `dist/` via `mpy-cross-multi`. `boot.py` is copied as plaintext (MicroPython requires the boot file uncompiled). `device_config.json` is copied alongside if present.

```shell
python tinker.py build [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `--micropython` | `1.28` | Target MicroPython version |
| `--march` | `xtensawin` | Target architecture (`xtensawin` = ESP32) |
| `--no-clean` | off | Skip removing `dist/` before building |

Examples:

```shell
# Standard build for ESP32
python tinker.py build

# Build against a specific MicroPython version, keep existing dist/ output
python tinker.py build --micropython 1.27 --no-clean

# Build for a different architecture (e.g. ESP32-S3 / Xtensa variants)
python tinker.py build --march xtensawin
```

Exits with code `1` and a summary if any file fails to compile.

---

### `upload`

Upload compiled firmware (or any local file/folder) to a device over serial, over a direct raw-REPL connection (does not require `mpremote`). Prints each file as it's sent (`[i/N] local -> remote`).

```shell
python tinker.py upload [OPTIONS] [PATH]
```

| Argument/Option | Default | Description |
|---|---|---|
| `PATH` | `./dist` | Local file or folder to upload |
| `--port`, `-p` | resolved (see [above](#config-resolution-order)) | Serial port |
| `--baud`, `-b` | `115200` | Baud rate (accepted for parity; the transfer always runs at 115200 — see note above) |
| `--reset` | off | Hard-reset the device via `esptool` before uploading |

Raw-REPL entry never soft-resets and always retries on a handshake race (same as [`device ls`](#device-ls)), so there is no longer a separate recovery flag - a plain `upload` (no `--reset`) already does what `--resume` used to.

Examples:

```shell
# Build then upload the default dist/ output, auto-detecting the port
python tinker.py build
python tinker.py upload

# Upload to a specific port
python tinker.py upload --port /dev/tty.usbserial-0001

# Device stuck / raw REPL entry exhausts its retries — hard-reset first
python tinker.py upload --reset

# Upload a single file instead of the whole dist/ folder
python tinker.py upload dist/main.mpy
```

On success, the resolved `port`/`baud`/`path` are saved to `.microweaver` as new defaults.

---

### `download`

Download the device's entire filesystem to a local folder via `mpremote fs cp -r :. <path>`.

```shell
python tinker.py download [OPTIONS] [PATH]
```

| Argument/Option | Default | Description |
|---|---|---|
| `PATH` | `./backup` | Local destination folder |
| `--port`, `-p` | resolved | Serial port |
| `--baud`, `-b` | `115200` | Baud rate (see note above — no effect) |

Examples:

```shell
# Back up the device filesystem to ./backup
python tinker.py download

# Back up to a named folder, e.g. before a risky firmware change
python tinker.py download ./backup-2026-08-05
```

If the destination folder is (or contains) the project root, `tinker.py` guards its own `.microweaver` file from being overwritten by the copy and restores it afterward.

---

### `watch`

Poll `app/`, `config/`, and the root source files (`_boot.py`, `main.py`, `boot.py`, `device_config.json`) for changes, and automatically re-run `build` + `upload` whenever one changes. Stop with `Ctrl+C`.

```shell
python tinker.py watch [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `--port`, `-p` | resolved (see [above](#config-resolution-order)) | Serial port |
| `--baud`, `-b` | `115200` | Baud rate (accepted for parity; see note above) |
| `--reset` | off | Hard-reset the device before each upload |
| `--micropython` | `1.28` | Target MicroPython version, passed to each rebuild |
| `--march` | `xtensawin` | Target architecture, passed to each rebuild |
| `--interval` | `1.0` | Polling interval in seconds |

Examples:

```shell
# Watch and auto rebuild+upload on save, auto-detecting the port
python tinker.py watch

# Watch a specific device, resetting it before each upload
python tinker.py watch --port /dev/tty.usbserial-0001 --reset
```

A failed build skips that upload but keeps watching; a failed upload is reported but also keeps watching. Uses the same port/baud resolution as `upload` on every cycle.

---

### `port`

List available serial ports.

```shell
python tinker.py port
```

Example output:

```
Port                       Description
-------------------------  ---------------------------
/dev/tty.usbserial-0001    USB Serial
```

Prints "No serial ports found." and exits `0` if nothing is connected.

---

### `config show`

Print the current saved defaults from `.microweaver`.

```shell
python tinker.py config show
```

---

### `config set`

Set default `port`/`baud`/`path`, saved to `.microweaver` for use by other commands.

```shell
python tinker.py config set [OPTIONS]
```

| Option | Description |
|---|---|
| `--port`, `-p` | Default serial port |
| `--baud`, `-b` | Default baud rate |
| `--path` | Default upload path |

Examples:

```shell
# Set a default port so you never have to pass --port again
python tinker.py config set --port /dev/tty.usbserial-0001

# Set multiple defaults at once
python tinker.py config set --port /dev/tty.usbserial-0001 --baud 115200 --path dist

# Run with no flags in an interactive shell to be prompted for each value
python tinker.py config set
```

Running with no flags and no TTY (e.g. in a script) errors out instead of hanging on a prompt.

---

### `device reset`

Hard-reset the device via `esptool`'s Python API.

```shell
python tinker.py device reset [OPTIONS]
```

| Option | Description |
|---|---|
| `--port`, `-p` | Serial port |

```shell
python tinker.py device reset
python tinker.py device reset --port /dev/tty.usbserial-0001
```

This bypasses the REPL entirely — unlike `mpremote reset` (which is just `machine.reset()` over a raw-REPL session), it still works when firmware is stuck in a blocking loop and unresponsive to Ctrl-C. Uses `esptool`'s board-aware `--after hard-reset` strategy so the chip reliably lands back in normal app mode instead of the ROM bootloader.

---

### `device info`

Show device hardware (chip/flash/MAC, read via `esptool`) and firmware (MicroPython `os.uname()` and reset/boot reason, read over a raw-REPL serial connection) details.

```shell
python tinker.py device info [OPTIONS]
```

| Option | Description |
|---|---|
| `--port`, `-p` | Serial port |

```shell
python tinker.py device info
```

Example output:

```
Field                Value
-------------------  ------------------------------------------------
Chip                 ESP32-S3
Features              WiFi, BLE
Crystal              40MHz
USB mode              USB-Serial/JTAG
MAC                   ac:15:18:xx:xx:xx
Flash Manufacturer   ef
Flash Device         4018
Flash Size           4MB
MicroPython          (sysname='esp32', nodename='esp32', ...)
Reset Reason         power_on
```

Chip/flash/MAC are read at the ROM bootloader level (same mechanism as `device reset`), so this works even if the firmware itself is unresponsive. The MicroPython and Reset Reason rows are opportunistic: if raw-REPL entry or the on-device read fails (after retrying), both report `unavailable (device unresponsive)` instead of failing the whole command. Reset Reason is read on-device via `app.services.reset.ResetService` (`power_on`, `software`, `watchdog`, `deep_sleep`, `sdio`, `intrusion`, `external`, `brownout`, or `unknown`).

---

### `device ls`

List files and folders on the device over a direct raw-REPL serial connection (does not require `mpremote`). Enters raw REPL without a soft reset - interrupting (ctrl-C) whatever is currently running already leaves the board at a clean idle prompt, so listing files has no reason to also reboot it (and, for firmware whose `main.py` runs forever, a soft reset would hang the handshake indefinitely). Opening the serial port can still trigger a board auto-reset on some ESP32 boards, racing the handshake against the reboot; on failure this retries up to `UPLOAD_RETRY_ATTEMPTS` times with the same linear backoff `upload --reset` uses, before falling back to the `device reset` hint.

```shell
python tinker.py device ls [OPTIONS] [PATH]
```

| Argument/Option | Default | Description |
|---|---|---|
| `PATH` | `:` (device root) | Device path to list |
| `--port`, `-p` | resolved | Serial port |

Examples:

```shell
# List the device root
python tinker.py device ls

# List a specific directory
python tinker.py device ls :app

# Against an explicit port
python tinker.py device ls --port /dev/tty.usbserial-0001 :config
```

---

### `device tree`

Show a recursive tree view of files and folders on the device over a direct raw-REPL serial connection (does not require `mpremote`). Walks the filesystem with repeated `DeviceTransport.ls()` calls in one raw-REPL session - `mpremote fs tree` has no raw-REPL equivalent to call directly, so the tree/connector formatting is reimplemented here to match. Same soft-reset-free raw-REPL entry and retry behavior as [`device ls`](#device-ls).

```shell
python tinker.py device tree [OPTIONS] [PATH]
```

| Argument/Option | Default | Description |
|---|---|---|
| `PATH` | `:` (device root) | Device path to show |
| `--port`, `-p` | resolved | Serial port |
| `--size`, `-s` | off | Show file size in bytes |
| `--human`, `-h` | off | Show file size, human-readable (e.g. `1.2K`) |

Examples:

```shell
# Full tree from the device root
python tinker.py device tree

# Tree with file sizes in bytes
python tinker.py device tree --size

# Tree with human-readable sizes, starting from a subdirectory
python tinker.py device tree --human :app
```

### `device test-adapter`

Bench-test a single adapter against real hardware without deploying the full app. Runs the adapter's `setup()` / `read()` (if it has one) / `deinit()` cycle over a raw-REPL serial connection and prints the result — useful for verifying wiring/config before wiring the adapter into a `PublishService`/`SubscribeService` run. Requires the adapter's module to already be present on the device (via `upload`).

```shell
python tinker.py device test-adapter [OPTIONS] MODULE
```

| Argument/Option | Default | Description |
|---|---|---|
| `MODULE` | (required) | Dotted path to the adapter class, e.g. `app.adapters.sensors.dht22.DHT22Adapter` |
| `--port`, `-p` | resolved | Serial port |

The adapter is instantiated with no arguments, so it uses its constructor's defaults (e.g. `DHT22Adapter(pin=4)`). Adapters without a `read()` method (actuators, indicators) print `no read() method` instead of failing.

Examples:

```shell
# Bench-test the DHT22 sensor adapter on the resolved port
python tinker.py device test-adapter app.adapters.sensors.dht22.DHT22Adapter

# Against an explicit port
python tinker.py device test-adapter --port /dev/tty.usbserial-0001 app.adapters.actuators.relay.RelayAdapter
```

## Common workflows

**First-time setup on a new device:**

```shell
python tinker.py port                          # find the port
python tinker.py config set --port /dev/tty.usbserial-0001
python tinker.py build
python tinker.py upload
python tinker.py device info                    # sanity-check the flash
```

**Iterating on firmware:**

```shell
python tinker.py build
python tinker.py upload --reset                  # reset first if the board is unresponsive
python tinker.py device tree                     # confirm what actually landed on-device

# or, to skip the manual build/upload cycle on every edit:
python tinker.py watch --reset
```

**Inspecting a device you didn't set up:**

```shell
python tinker.py port
python tinker.py device info --port /dev/tty.usbserial-0001
python tinker.py device tree --port /dev/tty.usbserial-0001 --human
```

**Backing up before a risky change:**

```shell
python tinker.py download ./backup-before-experiment
python tinker.py upload
# ...if it goes wrong:
python tinker.py upload ./backup-before-experiment --reset
```

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `ERROR: 'mpremote' not found on PATH.` | `pip install mpremote` |
| `ERROR: No serial ports found and none set in .microweaver.` | Connect the device, or run `tinker.py config set --port <port>` |
| `could not enter raw REPL` (upload/device ls/tree/info/health/rm/mkdir/test-adapter) | Firmware likely stuck or still rebooting — already retried automatically; if it still fails, retry with `upload --reset` or `device reset --port <port>` first |
| `mpremote fails with 'could not enter raw repl'` (fleet push/download/provision) | Firmware likely stuck or still rebooting — retry with `--reset` where supported, or `device reset --port <port>` first |
| `NOTE: mpremote ignores --baud ...` | Expected — `mpremote`'s CLI hardcodes 115200; not a bug in `tinker.py` |
| `device info` shows `MicroPython: unavailable` | Firmware busy/unresponsive after retrying — not related to `mpremote` being installed |
| Wrong device picked automatically | Only happens when exactly one port is present; unplug other USB-serial adapters or pass `--port` explicitly |
