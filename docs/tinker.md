# `tinker.py` CLI Reference

`tinker.py` builds, uploads, downloads, and manages firmware for ESP32 (and other MicroPython-supported) devices. It is a [Typer](https://typer.tiangolo.com/) CLI built on top of [`esptool`](https://github.com/espressif/esptool) (chip-level access) and [`mpremote`](https://github.com/micropython/micropython/tree/master/tools/mpremote) (filesystem/REPL access over serial).

- [Prerequisites](#prerequisites)
- [Global concepts](#global-concepts)
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
- [Common workflows](#common-workflows)
- [Troubleshooting](#troubleshooting)

## Prerequisites

| Tool | Required for | Install |
|---|---|---|
| `mpy-cross-multi` | `build` | bundled with the project's build deps |
| `mpremote` | `upload`, `download`, `device info` (firmware read), `device ls`, `device tree` | `pip install mpremote` |
| `esptool` (Python API) | `device reset`, `device info` (chip read) | installed as a project dependency, no separate CLI install needed |

`upload`, `download`, `device ls`, and `device tree` check for `mpremote` on `PATH` up front and print an install hint if it's missing, rather than failing with a raw `FileNotFoundError`.

## Global concepts

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

Upload compiled firmware (or any local file/folder) to a device over serial, via `mpremote fs cp -r`.

```shell
python tinker.py upload [OPTIONS] [PATH]
```

| Argument/Option | Default | Description |
|---|---|---|
| `PATH` | `./dist` | Local file or folder to upload |
| `--port`, `-p` | resolved (see [above](#config-resolution-order)) | Serial port |
| `--baud`, `-b` | `115200` | Baud rate (accepted for parity; `mpremote` ignores it — see note above) |
| `--reset` | off | Hard-reset the device via `esptool` before uploading |

Examples:

```shell
# Build then upload the default dist/ output, auto-detecting the port
python tinker.py build
python tinker.py upload

# Upload to a specific port
python tinker.py upload --port /dev/tty.usbserial-0001

# Device stuck / mpremote can't enter raw REPL — hard-reset first
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

Show device hardware (chip/flash/MAC, read via `esptool`) and firmware (MicroPython `os.uname()` and reset/boot reason, read via `mpremote`) details.

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

Chip/flash/MAC are read at the ROM bootloader level (same mechanism as `device reset`), so this works even if the firmware itself is unresponsive. The MicroPython and Reset Reason rows only appear if `mpremote` is installed and the firmware answers within 10 seconds; otherwise each reports `unavailable (device unresponsive)` or `unavailable (timed out, device may be busy)`. Reset Reason is read on-device via `app.services.reset.ResetService` (`power_on`, `software`, `watchdog`, `deep_sleep`, `sdio`, `intrusion`, `external`, `brownout`, or `unknown`).

---

### `device ls`

List files and folders on the device via `mpremote fs ls`.

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

Show a recursive tree view of files and folders on the device via `mpremote fs tree`.

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
| `mpremote fails with 'could not enter raw repl'` | Firmware likely stuck — retry with `upload --reset`, or run `device reset` first |
| `NOTE: mpremote ignores --baud ...` | Expected — `mpremote`'s CLI hardcodes 115200; not a bug in `tinker.py` |
| `device info` shows `MicroPython: unavailable` | `mpremote` not installed, or firmware busy/unresponsive within the 10s timeout |
| Wrong device picked automatically | Only happens when exactly one port is present; unplug other USB-serial adapters or pass `--port` explicitly |
