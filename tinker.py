#!/usr/bin/env python3
"""Build, upload, and manage microweaver firmware."""

import configparser
import json
import shutil
import subprocess  # nosec B404
import sys
import time
import tomllib
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

import typer
from esptool.cmds import _get_flash_info as get_flash_info
from esptool.cmds import attach_flash, detect_chip, reset_chip
from esptool.logger import log as esptool_log
from esptool.util import FatalError
from serial.tools import list_ports

from config.app import ConfigError, Setting
from device_transport import DeviceExecError, DeviceTransport, RawReplEntryError

ROOT = Path(__file__).parent
DIST = ROOT / "dist"
BACKUP = ROOT / "backup"
CONFIG_PATH = ROOT / ".microweaver"
DEFAULT_BAUD = 115200
UPLOAD_RESET_SETTLE_SECONDS = 1.5
UPLOAD_RETRY_ATTEMPTS = 4
MPREMOTE_RAW_REPL_ERROR = "could not enter raw repl"

PACKAGE_DIRS = ["app", "config"]
ROOT_FILES_COMPILE = ["_boot.py", "main.py"]
ROOT_FILES_COPY = ["boot.py"]


def _read_version() -> str:
    """Read the project version from pyproject.toml next to this script.

    Not read via importlib.metadata since tinker.py is normally run in
    place rather than pip-installed as a package.
    """
    try:
        with (Path(__file__).parent / "pyproject.toml").open("rb") as f:
            data = tomllib.load(f)
        return data["tool"]["poetry"]["version"]
    except (OSError, tomllib.TOMLDecodeError, KeyError):
        return "unknown"


VERSION = _read_version()

app = typer.Typer(
    no_args_is_help=True,
    help="Build, upload, and manage microweaver firmware.",
)
config_app = typer.Typer(
    no_args_is_help=True, help="View or set default port/baud/path."
)
app.add_typer(config_app, name="config")
device_app = typer.Typer(no_args_is_help=True, help="Interrupt or reset the device.")
app.add_typer(device_app, name="device")
fleet_app = typer.Typer(no_args_is_help=True, help="Push a build to multiple devices.")
app.add_typer(fleet_app, name="fleet")


def _version_callback(value: bool) -> None:
    if value:
        print(f"tinker.py {VERSION}")
        raise typer.Exit()


@app.callback()
def main(
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the tinker.py version and exit.",
    ),
) -> None:
    pass


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    cp = configparser.ConfigParser()
    cp.read(CONFIG_PATH)
    return dict(cp["default"]) if cp.has_section("default") else {}


def save_config(**values) -> dict:
    cp = configparser.ConfigParser()
    if CONFIG_PATH.exists():
        cp.read(CONFIG_PATH)
    if not cp.has_section("default"):
        cp.add_section("default")
    saved = {}
    for key, value in values.items():
        if value is not None:
            cp.set("default", key, str(value))
            saved[key] = value
    with CONFIG_PATH.open("w") as f:
        cp.write(f)
    return saved


def print_table(columns: list, rows) -> None:
    rows = [[str(c) for c in row] for row in rows]
    widths = [
        max(len(col), *(len(row[i]) for row in rows)) if rows else len(col)
        for i, col in enumerate(columns)
    ]

    def fmt_row(cells):
        return "  ".join(cell.ljust(w) for cell, w in zip(cells, widths)).rstrip()

    print(fmt_row(columns))
    print("  ".join("-" * w for w in widths))
    for row in rows:
        print(fmt_row(row))


def prompt_for_port() -> str:
    """Interactively resolve a port by scanning available serial ports."""
    ports = sorted(list_ports.comports())
    if not ports:
        print(
            "ERROR: No serial ports found and none set in .microweaver. "
            "Connect a device and retry, or run 'tinker.py config set "
            "--port <port>'.",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)

    if not sys.stdin.isatty():
        print(
            "ERROR: No --port given and none set in .microweaver. Run "
            "'tinker.py port' to list ports, or 'tinker.py config set "
            "--port <port>'.",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)

    if len(ports) == 1:
        print(f"Using the only available port: {ports[0].device}")
        return ports[0].device

    rows = [
        (i + 1, p.device, p.description if p.description != "n/a" else "")
        for i, p in enumerate(ports)
    ]
    print_table(["No", "Port", "Description"], rows)
    choice = typer.prompt(f"Select a port (1-{len(ports)})", type=int)
    while not 1 <= choice <= len(ports):
        print(f"Enter a number between 1 and {len(ports)}.", file=sys.stderr)
        choice = typer.prompt(f"Select a port (1-{len(ports)})", type=int)
    return ports[choice - 1].device


def connect_esp(port_name: str):
    """Connect to a device via esptool's Python API, raising typer.Exit on failure."""
    esptool_log.set_verbosity("silent")
    try:
        return detect_chip(port=port_name)
    except FatalError as exc:
        print(
            f"ERROR: could not connect to {port_name}:\n{exc}",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)


def hard_reset(port_name: str) -> None:
    """Reset the board via esptool.

    Bypasses the REPL entirely (unlike mpremote's own 'reset' shortcut, which
    is just `machine.reset()` over a raw-REPL session) so it still works when
    firmware is stuck in a blocking loop and won't respond to Ctrl-C.

    esptool (not a raw DTR/RTS pulse) because it ships board-aware reset
    strategies for the various auto-reset circuit wirings out there, and
    --after hard-reset guarantees the chip lands back in normal app mode
    rather than getting stranded in the ROM download bootloader, which a
    mistimed/wrong-polarity manual pulse can do.
    """
    esp = connect_esp(port_name)
    try:
        reset_chip(esp, "hard-reset")
    except FatalError as exc:
        print(
            f"ERROR: could not reset {port_name}:\n{exc}",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)
    finally:
        esp._port.close()


def _is_raw_repl_failure(output: str) -> bool:
    """Check whether mpremote failed to switch the board into raw REPL."""
    return MPREMOTE_RAW_REPL_ERROR in output.lower()


def _print_mpremote_failure(
    resolved_port: str, *, allow_reset_hint: bool, output: str
) -> None:
    """Print a friendlier recovery hint for common mpremote failures."""
    if _is_raw_repl_failure(output):
        print(
            f"ERROR: mpremote could not enter raw REPL on {resolved_port}. "
            "Firmware may be stuck or the board may still be rebooting.",
            file=sys.stderr,
        )
        if allow_reset_hint:
            print(
                f"Retry with 'python tinker.py device reset --port {resolved_port}' "
                "or rerun this command with '--reset' where supported.",
                file=sys.stderr,
            )
        else:
            print(
                f"Retry with 'python tinker.py device reset --port {resolved_port}' "
                "and try again.",
                file=sys.stderr,
            )
        return

    if output:
        print(output, end="", file=sys.stderr)


def _run_mpremote_cmd(
    cmd: list[str], resolved_port: str, *, allow_reset_hint: bool = False
) -> "subprocess.CompletedProcess[str]":
    """Run a non-interactive mpremote command and normalize raw-REPL errors."""
    result = subprocess.run(  # nosec B603
        cmd,
        capture_output=True,
        text=True,
    )
    stdout = result.stdout if isinstance(result.stdout, str) else ""
    stderr = result.stderr if isinstance(result.stderr, str) else ""

    if result.returncode == 0:
        if stdout:
            print(stdout, end="")
        if stderr:
            print(stderr, end="", file=sys.stderr)
        return result

    combined = "".join(part for part in (stdout, stderr) if part)
    _print_mpremote_failure(
        resolved_port, allow_reset_hint=allow_reset_hint, output=combined
    )
    return result


def _run_mpremote_interactive(
    cmd: list[str], resolved_port: str
) -> "subprocess.CompletedProcess[str]":
    """Run an interactive mpremote command while still catching raw-REPL errors."""
    result = subprocess.run(  # nosec B603
        cmd,
        stderr=subprocess.PIPE,
        text=True,
    )
    stderr = result.stderr if isinstance(result.stderr, str) else ""
    if result.returncode != 0:
        _print_mpremote_failure(
            resolved_port,
            allow_reset_hint=False,
            output=stderr,
        )
    elif stderr:
        print(stderr, end="", file=sys.stderr)
    return result


def _mpremote_connect_cmd(resolved_port: str) -> list[str]:
    """Build an mpremote connect command prefix for this port."""
    return ["mpremote", "connect", resolved_port]


def compile_file(src: Path, dst: Path, mp_version: str, march: str) -> bool:
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "mpy-cross-multi",
        "--micropython",
        mp_version,
        f"-march={march}",
        "-o",
        str(dst),
        str(src),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)  # nosec B603
    if result.returncode != 0:
        print(f"ERROR {src}: {result.stderr.strip()}", file=sys.stderr)
        return False
    print(f"  {src.relative_to(ROOT)} -> {dst.relative_to(ROOT)}")
    return True


def _clean_dist() -> bool:
    """Remove dist/ if it exists. Returns True if anything was removed."""
    if DIST.exists():
        shutil.rmtree(DIST)
        print("Cleaned dist/")
        return True
    return False


@app.command()
def clean(
    backup: bool = typer.Option(
        False, "--backup", help="Also remove backup/ (default: only dist/)"
    ),
) -> None:
    """Remove build artifacts from dist/ (and optionally backup/)."""
    cleaned = _clean_dist()
    if backup and BACKUP.exists():
        shutil.rmtree(BACKUP)
        print("Cleaned backup/")
        cleaned = True
    if not cleaned:
        print("Nothing to clean.")


@app.command()
def build(
    micropython: str = typer.Option("1.28", help="Target MicroPython version"),
    march: str = typer.Option(
        "xtensawin", help="Target architecture (default: xtensawin for ESP32)"
    ),
    no_clean: bool = typer.Option(
        False, "--no-clean", help="Skip removing dist/ before building"
    ),
) -> None:
    """Compile firmware .py files to .mpy bytecode in dist/."""
    if not no_clean:
        _clean_dist()

    errors = 0

    for pkg in PACKAGE_DIRS:
        for src in sorted((ROOT / pkg).rglob("*.py")):
            dst = DIST / src.relative_to(ROOT).with_suffix(".mpy")
            if not compile_file(src, dst, micropython, march):
                errors += 1

    for name in ROOT_FILES_COMPILE:
        src = ROOT / name
        dst = DIST / src.with_suffix(".mpy").name
        if not compile_file(src, dst, micropython, march):
            errors += 1

    for name in ROOT_FILES_COPY:
        src = ROOT / name
        dst = DIST / src.name
        DIST.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        print(f"  {src.relative_to(ROOT)} -> dist/{src.name}")

    config_src = ROOT / "device_config.json"
    if config_src.exists():
        shutil.copy2(config_src, DIST / "device_config.json")
        print("  device_config.json -> dist/device_config.json")
    else:
        print("  device_config.json not found, skipped")

    if errors:
        print(f"\n{errors} file(s) failed.", file=sys.stderr)
        raise typer.Exit(code=1)
    print("\nDone. Output: dist/")


def _run_upload_cmd(
    cmd: list[str], resolved_port: str, attempts: int
) -> "subprocess.CompletedProcess[str]":
    """Run the mpremote fs cp command, retrying 'could not enter raw repl'.

    A hard reset races mpremote's raw-REPL handshake against the board
    rebooting. If the device has no WiFi credentials configured it also
    boots into provisioning mode - starting its own AP and HTTP server -
    which keeps the serial port busy longer than a normal boot, so this
    failure right after --reset is usually transient rather than fatal.
    Retry with a linear backoff (longer waits on later attempts) before
    giving up.
    """
    result = _run_mpremote_cmd(cmd, resolved_port, allow_reset_hint=True)
    for attempt in range(2, attempts + 1):
        if result.returncode == 0:
            break
        combined = "".join(
            part
            for part in (
                result.stdout if isinstance(result.stdout, str) else "",
                result.stderr if isinstance(result.stderr, str) else "",
            )
            if part
        )
        if not _is_raw_repl_failure(combined):
            break
        print(
            f"NOTE: upload failed (raw-REPL race after reset), "
            f"retrying ({attempt}/{attempts})...",
            file=sys.stderr,
        )
        time.sleep(UPLOAD_RESET_SETTLE_SECONDS * (attempt - 1))
        result = _run_mpremote_cmd(cmd, resolved_port, allow_reset_hint=True)
    return result


@app.command()
def upload(
    port: Optional[str] = typer.Option(
        None, "--port", "-p", help="Serial port of device (see 'tinker.py port')"
    ),
    baud: Optional[int] = typer.Option(None, "--baud", "-b", help="Baud rate"),
    reset: bool = typer.Option(
        False,
        "--reset",
        help=(
            "Hard-reset the device before uploading. Use this if the device "
            "is stuck (e.g. raw REPL entry fails after several retries)."
        ),
    ),
    path: Optional[Path] = typer.Argument(
        None, help="Local file/folder to upload (default: ./dist)"
    ),
) -> None:
    """Upload compiled firmware to a device over serial."""
    # Resolution order: CLI flag > .microweaver > hardcoded default.
    config = load_config()
    resolved_port = port or config.get("port")
    resolved_baud = baud if baud is not None else int(config.get("baud", DEFAULT_BAUD))
    resolved_path = path or (Path(config["path"]) if "path" in config else DIST)

    if resolved_port is None:
        resolved_port = prompt_for_port()
        port = resolved_port

    if not resolved_path.exists():
        print(f"ERROR: {resolved_path} does not exist.", file=sys.stderr)
        raise typer.Exit(code=1)

    # DeviceTransport always runs at 115200 baud; --baud is accepted for
    # interface/config-file compatibility but has no effect on the transfer.
    if resolved_baud != 115200:
        print(
            f"NOTE: upload ignores --baud (requested {resolved_baud}), "
            "connection always runs at 115200.",
            file=sys.stderr,
        )

    if reset:
        print(f"Resetting {resolved_port}...")
        hard_reset(resolved_port)
        time.sleep(UPLOAD_RESET_SETTLE_SECONDS)

    try:
        with _raw_repl_session(resolved_port, "upload") as transport:
            if resolved_path.is_dir():
                transport.put_dir(resolved_path, ":", on_file=_print_upload_file)
            else:
                transport.put_file(
                    resolved_path, f":{resolved_path.name}", on_start=_print_upload_file
                )
    except RawReplEntryError as exc:
        _print_raw_repl_failure(resolved_port)
        raise typer.Exit(code=1) from exc
    except DeviceExecError as exc:
        print(f"ERROR: {exc.stderr}", file=sys.stderr)
        raise typer.Exit(code=1) from exc

    save_config(port=port, baud=baud, path=path)
    print(f"\nUploaded {resolved_path} -> {resolved_port}")


def _print_upload_file(
    local: Path, remote: str, index: int | None = None, total: int | None = None
) -> None:
    prefix = f"[{index}/{total}] " if index is not None else ""
    print(f"{prefix}{local} -> {remote}")


@fleet_app.command("push")
def fleet_push(
    ports: Optional[list[str]] = typer.Option(
        None,
        "--port",
        "-p",
        help="Serial port to push to (repeatable). Default: all detected ports.",
    ),
    baud: Optional[int] = typer.Option(None, "--baud", "-b", help="Baud rate"),
    reset: bool = typer.Option(
        False,
        "--reset",
        help="Hard-reset each device before uploading (recommended for a fleet, "
        "since a stuck device shouldn't block the others).",
    ),
    path: Optional[Path] = typer.Argument(
        None, help="Local file/folder to upload (default: ./dist)"
    ),
) -> None:
    """Upload compiled firmware to every given (or detected) device over serial."""
    if shutil.which("mpremote") is None:
        print(
            "ERROR: 'mpremote' not found on PATH. Install it with "
            "'pip install mpremote'.",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)

    resolved_ports = (
        list(ports) if ports else [p.device for p in sorted(list_ports.comports())]
    )
    if not resolved_ports:
        print(
            "ERROR: no --port given and no serial ports detected. Connect "
            "device(s) and retry, or pass --port explicitly.",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)

    resolved_path = path or DIST
    if not resolved_path.exists():
        print(f"ERROR: {resolved_path} does not exist.", file=sys.stderr)
        raise typer.Exit(code=1)

    resolved_baud = baud if baud is not None else DEFAULT_BAUD
    if resolved_baud != 115200:
        print(
            f"NOTE: mpremote ignores --baud (requested {resolved_baud}), "
            "connection always runs at 115200.",
            file=sys.stderr,
        )

    src = f"{resolved_path}/." if resolved_path.is_dir() else str(resolved_path)
    attempts = UPLOAD_RETRY_ATTEMPTS if reset else 1

    print(
        f"Pushing {resolved_path} to {len(resolved_ports)} device(s): "
        f"{', '.join(resolved_ports)}"
    )

    results = []
    for port_name in resolved_ports:
        print(f"\n== {port_name} ==")
        if reset:
            print(f"Resetting {port_name}...")
            try:
                hard_reset(port_name)
            except typer.Exit:
                results.append((port_name, False))
                continue
            time.sleep(UPLOAD_RESET_SETTLE_SECONDS)

        cmd = _mpremote_connect_cmd(port_name) + ["fs", "cp", "-r", src, ":"]
        result = _run_upload_cmd(cmd, port_name, attempts)
        results.append((port_name, result.returncode == 0))

    print()
    print_table(
        ["Port", "Result"],
        [(p, "OK" if ok else "FAILED") for p, ok in results],
    )

    failed = [p for p, ok in results if not ok]
    if failed:
        print(f"\n{len(failed)}/{len(results)} device(s) failed.", file=sys.stderr)
        raise typer.Exit(code=1)
    print(f"\nPushed {resolved_path} -> {len(results)} device(s).")


@app.command()
def download(
    port: Optional[str] = typer.Option(
        None, "--port", "-p", help="Serial port of device (see 'tinker.py port')"
    ),
    baud: Optional[int] = typer.Option(None, "--baud", "-b", help="Baud rate"),
    path: Path = typer.Argument(
        BACKUP,
        help="Local destination folder to save device files into "
        "(relative or absolute path, default: ./backup)",
    ),
) -> None:
    """Download the device's filesystem to a local folder."""
    if shutil.which("mpremote") is None:
        print(
            "ERROR: 'mpremote' not found on PATH. Install it with "
            "'pip install mpremote'.",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)

    # Resolution order: CLI flag > .microweaver > hardcoded default.
    config = load_config()
    resolved_port = port or config.get("port")
    resolved_baud = baud if baud is not None else int(config.get("baud", DEFAULT_BAUD))

    if resolved_port is None:
        resolved_port = prompt_for_port()
        port = resolved_port

    # mpremote's CLI hardcodes 115200 baud (no override flag exists upstream
    # as of 1.28.0); --baud is accepted for interface parity but has no
    # effect on the actual transfer today.
    if resolved_baud != 115200:
        print(
            f"NOTE: mpremote ignores --baud (requested {resolved_baud}), "
            "connection always runs at 115200.",
            file=sys.stderr,
        )

    path.mkdir(parents=True, exist_ok=True)

    # mpremote's fs cp has no include/exclude filter, so if the destination
    # is (or contains) the project root, guard our own config file from
    # being clobbered by whatever the copy pulls in.
    guard_path = path / CONFIG_PATH.name
    guard_backup = guard_path.read_bytes() if guard_path.exists() else None

    cmd = ["mpremote", "connect", resolved_port, "fs", "cp", "-r", ":.", str(path)]
    result = _run_mpremote_cmd(cmd, resolved_port)

    if guard_backup is not None:
        guard_path.write_bytes(guard_backup)

    if result.returncode != 0:
        raise typer.Exit(code=result.returncode)

    save_config(port=port, baud=baud)
    print(f"\nDownloaded {resolved_port} -> {path}")


PROVISION_FIELDS = [
    # (json key, prompt label, default, is_secret)
    ("wifi_ssid", "WiFi SSID", "", False),
    ("wifi_password", "WiFi password", "", True),
    ("mqtt_broker", "MQTT broker", "localhost", False),
    ("mqtt_port", "MQTT port", 1883, False),
    ("mqtt_client_id", "MQTT client id", "microweaver", False),
    ("mqtt_topic_pub", "MQTT publish topic", "command/control/room/light", False),
    ("mqtt_topic_sub", "MQTT subscribe topic", "data/sensor/room/temperature", False),
    ("mqtt_username", "MQTT username", "", False),
    ("mqtt_password", "MQTT password", "", True),
]


def _load_provision_defaults() -> dict:
    """Seed prompt defaults from the device's own device_config.json, falling
    back to the shipped example when it doesn't exist yet."""
    config_path = ROOT / "device_config.json"
    defaults_path = (
        config_path if config_path.exists() else ROOT / "device_config.json.example"
    )
    if not defaults_path.exists():
        return {}
    with defaults_path.open() as f:
        return json.load(f)


def _prompt_missing_fields(given: dict, defaults: dict) -> None:
    """Fill any None values in `given` (in place) by prompting interactively."""
    print("Provisioning over serial. Press Enter to accept the default.\n")
    for key, label, fallback, secret in PROVISION_FIELDS:
        if given[key] is not None:
            continue
        given[key] = typer.prompt(
            label,
            default=defaults.get(key, fallback),
            type=int if isinstance(fallback, int) else str,
            hide_input=secret,
        )


def _require_tty_for_missing(missing: list) -> None:
    if missing and not sys.stdin.isatty():
        flags = ", ".join(f"--{key.replace('_', '-')}" for key in missing)
        print(f"ERROR: no TTY to prompt for: {flags}.", file=sys.stderr)
        raise typer.Exit(code=1)


@app.command()
def provision(
    port: Optional[str] = typer.Option(
        None, "--port", "-p", help="Serial port of device (see 'tinker.py port')"
    ),
    baud: Optional[int] = typer.Option(None, "--baud", "-b", help="Baud rate"),
    wifi_ssid: Optional[str] = typer.Option(None, help="WiFi SSID"),
    wifi_password: Optional[str] = typer.Option(None, help="WiFi password"),
    mqtt_broker: Optional[str] = typer.Option(None, help="MQTT broker host"),
    mqtt_port: Optional[int] = typer.Option(None, help="MQTT broker port"),
    mqtt_client_id: Optional[str] = typer.Option(None, help="MQTT client id"),
    mqtt_topic_pub: Optional[str] = typer.Option(None, help="MQTT publish topic"),
    mqtt_topic_sub: Optional[str] = typer.Option(None, help="MQTT subscribe topic"),
    mqtt_username: Optional[str] = typer.Option(None, help="MQTT username"),
    mqtt_password: Optional[str] = typer.Option(None, help="MQTT password"),
) -> None:
    """Prompt for WiFi/MQTT settings and push a generated device_config.json.

    Bench/headless alternative to the SoftAP captive-portal setup flow: no
    phone or laptop needs to join the device's access point, since settings
    are entered locally and pushed over the same serial connection used by
    upload/download.
    """
    if shutil.which("mpremote") is None:
        print(
            "ERROR: 'mpremote' not found on PATH. Install it with "
            "'pip install mpremote'.",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)

    # Resolution order: CLI flag > .microweaver > hardcoded default.
    config = load_config()
    resolved_port = port or config.get("port")
    resolved_baud = baud if baud is not None else int(config.get("baud", DEFAULT_BAUD))

    if resolved_port is None:
        resolved_port = prompt_for_port()
        port = resolved_port

    # mpremote's CLI hardcodes 115200 baud (no override flag exists upstream
    # as of 1.28.0); --baud is accepted for interface parity but has no
    # effect on the actual transfer today.
    if resolved_baud != 115200:
        print(
            f"NOTE: mpremote ignores --baud (requested {resolved_baud}), "
            "connection always runs at 115200.",
            file=sys.stderr,
        )

    given = {
        "wifi_ssid": wifi_ssid,
        "wifi_password": wifi_password,
        "mqtt_broker": mqtt_broker,
        "mqtt_port": mqtt_port,
        "mqtt_client_id": mqtt_client_id,
        "mqtt_topic_pub": mqtt_topic_pub,
        "mqtt_topic_sub": mqtt_topic_sub,
        "mqtt_username": mqtt_username,
        "mqtt_password": mqtt_password,
    }
    missing = [key for key, value in given.items() if value is None]
    _require_tty_for_missing(missing)

    defaults = _load_provision_defaults()
    if missing:
        _prompt_missing_fields(given, defaults)

    config_path = ROOT / "device_config.json"
    merged = dict(defaults)
    merged.update(given)

    try:
        Setting(config_path=str(config_path)).save(**merged)
    except ConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise typer.Exit(code=1)

    cmd = [
        "mpremote",
        "connect",
        resolved_port,
        "fs",
        "cp",
        str(config_path),
        ":device_config.json",
    ]
    result = _run_mpremote_cmd(cmd, resolved_port)
    if result.returncode != 0:
        raise typer.Exit(code=result.returncode)

    save_config(port=port, baud=baud)
    print(f"\nProvisioned {resolved_port} with {config_path.name}")


def _watched_files() -> list:
    """Collect the same source files build() compiles/copies, for change detection."""
    files = []
    for pkg in PACKAGE_DIRS:
        files.extend(sorted((ROOT / pkg).rglob("*.py")))
    for name in ROOT_FILES_COMPILE + ROOT_FILES_COPY:
        path = ROOT / name
        if path.exists():
            files.append(path)
    config_src = ROOT / "device_config.json"
    if config_src.exists():
        files.append(config_src)
    return files


def _scan_mtimes(paths: list) -> dict:
    """Snapshot each path's mtime, skipping any removed mid-scan."""
    snapshot = {}
    for path in paths:
        try:
            snapshot[path] = path.stat().st_mtime
        except FileNotFoundError:
            continue
    return snapshot


def _rebuild_and_upload(
    port: Optional[str],
    baud: Optional[int],
    reset: bool,
    micropython: str,
    march: str,
) -> None:
    """Run build() then upload() for watch(), skipping upload if the build failed."""
    print("\nChange detected, rebuilding...")
    try:
        build(micropython=micropython, march=march, no_clean=False)
    except typer.Exit as exc:
        if exc.exit_code:
            print("Build failed, skipping upload.", file=sys.stderr)
            return

    try:
        upload(port=port, baud=baud, reset=reset, path=None)
    except typer.Exit as exc:
        if exc.exit_code:
            print("Upload failed.", file=sys.stderr)


@app.command()
def watch(
    port: Optional[str] = typer.Option(
        None, "--port", "-p", help="Serial port of device (see 'tinker.py port')"
    ),
    baud: Optional[int] = typer.Option(None, "--baud", "-b", help="Baud rate"),
    reset: bool = typer.Option(
        False, "--reset", help="Hard-reset the device before each upload"
    ),
    micropython: str = typer.Option("1.28", help="Target MicroPython version"),
    march: str = typer.Option(
        "xtensawin", help="Target architecture (default: xtensawin for ESP32)"
    ),
    interval: float = typer.Option(
        1.0, "--interval", help="Polling interval in seconds"
    ),
) -> None:
    """Watch app/, config/, and root source files; rebuild + upload on change."""
    watched = _watched_files()
    if not watched:
        print("ERROR: no source files found to watch.", file=sys.stderr)
        raise typer.Exit(code=1)

    print(
        f"Watching {len(watched)} file(s) in app/, config/, and root sources. "
        "Press Ctrl+C to stop."
    )
    snapshot = _scan_mtimes(watched)

    try:
        while True:
            time.sleep(interval)
            current = _scan_mtimes(_watched_files())
            if current == snapshot:
                continue
            snapshot = current
            _rebuild_and_upload(port, baud, reset, micropython, march)
    except KeyboardInterrupt:
        print("\nStopped watching.")


@config_app.command("show")
def config_show() -> None:
    """Print current .microweaver defaults."""
    config = load_config()
    if not config:
        print("No config file found.")
        raise typer.Exit(code=0)
    print_table(["Key", "Value"], config.items())


@config_app.command("set")
def config_set(
    port: Optional[str] = typer.Option(
        None, "--port", "-p", help="Default serial port"
    ),
    baud: Optional[int] = typer.Option(None, "--baud", "-b", help="Default baud rate"),
    path: Optional[Path] = typer.Option(None, "--path", help="Default upload path"),
) -> None:
    """Set default port/baud/path in .microweaver."""
    if port is None and baud is None and path is None:
        if not sys.stdin.isatty():
            print("Nothing to set. Pass --port/--baud/--path.", file=sys.stderr)
            raise typer.Exit(code=1)

        current = load_config()
        port = typer.prompt("Port", default=current.get("port", ""))
        baud = typer.prompt(
            "Baud", default=current.get("baud", str(DEFAULT_BAUD)), type=int
        )
        path = typer.prompt("Path", default=current.get("path", str(DIST)))
        port = port or None
        path = Path(path) if path else None

    saved = save_config(port=port, baud=baud, path=path)
    if not saved:
        print("Nothing to set. Pass --port/--baud/--path.", file=sys.stderr)
        raise typer.Exit(code=1)
    print_table(["Key", "Value"], saved.items())
    print(f"\nSaved to {CONFIG_PATH.relative_to(ROOT)}")


@device_app.command("reset")
def device_reset(
    port: Optional[str] = typer.Option(
        None, "--port", "-p", help="Serial port of device"
    ),
) -> None:
    """Hard-reset the device via esptool — works even if firmware is stuck."""
    config = load_config()
    resolved_port = port or config.get("port")
    if resolved_port is None:
        resolved_port = prompt_for_port()

    hard_reset(resolved_port)
    print(f"Reset {resolved_port}")


@device_app.command("info")
def device_info(
    port: Optional[str] = typer.Option(
        None, "--port", "-p", help="Serial port of device"
    ),
) -> None:
    """Show device hardware (chip/flash/MAC) and firmware (MicroPython) details."""
    config = load_config()
    resolved_port = port or config.get("port")
    if resolved_port is None:
        resolved_port = prompt_for_port()

    # detect_chip connects at the ROM bootloader level, so it works even if
    # the firmware/REPL is unresponsive (same reasoning as hard_reset()).
    esp = connect_esp(resolved_port)
    rows = []
    try:
        rows.append(("Chip", esp.CHIP_NAME))
        rows.append(("Features", ", ".join(esp.get_chip_features())))
        rows.append(("Crystal", f"{esp.get_crystal_freq()}MHz"))
        usb_mode = esp.get_usb_mode()
        if usb_mode is not None:
            rows.append(("USB mode", usb_mode))

        eui64 = esp.read_mac("EUI64")
        mac = eui64 if eui64 else esp.read_mac("BASE_MAC")
        rows.append(("MAC", ":".join(f"{x:02x}" for x in mac)))

        attach_flash(esp)
        manufacturer_id, device_id, flash_size = get_flash_info(esp)
        rows.append(("Flash Manufacturer", f"{manufacturer_id:02x}"))
        rows.append(("Flash Device", f"{device_id:04x}"))
        rows.append(("Flash Size", flash_size or "Unknown"))

        reset_chip(esp, "hard-reset")
    except FatalError as exc:
        print(
            f"ERROR: could not read chip info:\n{exc}",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)
    finally:
        esp._port.close()

    try:
        with _raw_repl_session(resolved_port, "device info") as transport:
            uname = transport.exec("import os; print(os.uname())")
            reset_reason = transport.exec(
                "from app.services.reset import ResetService; "
                "print(ResetService().read())"
            )
        rows.append(("MicroPython", uname.strip()))
        rows.append(("Reset Reason", reset_reason.strip()))
    except (RawReplEntryError, DeviceExecError):
        rows.append(("MicroPython", "unavailable (device unresponsive)"))
        rows.append(("Reset Reason", "unavailable (device unresponsive)"))

    if not rows:
        print("No device details could be read.")
        raise typer.Exit(code=1)

    print_table(["Field", "Value"], rows)


@device_app.command("health")
def device_health(
    port: Optional[str] = typer.Option(
        None, "--port", "-p", help="Serial port of device"
    ),
) -> None:
    """Fetch and print a HealthCheckService report from the device.

    Builds a fresh WiFiService/MetricsService/HealthCheckService on-device
    (same as PublishService/SubscribeService wiring) and polls it once, so no
    MQTT subscriber is needed to see the current health snapshot. Metrics
    reflect this fresh instance, not the running loop's accumulated counters.
    """
    config = load_config()
    resolved_port = port or config.get("port")
    if resolved_port is None:
        resolved_port = prompt_for_port()

    script = (
        "import json; "
        "from app.services.health import HealthCheckService; "
        "from app.services.metrics import MetricsService; "
        "from app.services.wifi import WiFiService; "
        "from config.app import Setting; "
        "setting = Setting().get_settings(); "
        "wifi = WiFiService(setting.WIFI_SSID, setting.WIFI_PASSWORD); "
        "metrics = MetricsService(); "
        "health = HealthCheckService("
        "app_version=setting.APP_VERSION, metrics=metrics); "
        "health.register('wifi', wifi.is_connected); "
        "health.poll(); "
        "print(json.dumps(health.report()))"
    )
    try:
        with _raw_repl_session(resolved_port, "device health") as transport:
            output = transport.exec(script)
    except RawReplEntryError as exc:
        _print_raw_repl_failure(resolved_port)
        raise typer.Exit(code=1) from exc
    except DeviceExecError as exc:
        print(f"ERROR: {exc.stderr}", file=sys.stderr)
        raise typer.Exit(code=1) from exc

    # Any startup print (e.g. LogService) before the final JSON line is
    # discarded, matching the previous mpremote-exec-based behavior.
    raw = output.strip().splitlines()[-1] if output.strip() else ""

    try:
        report = json.loads(raw)
    except ValueError:
        print(f"ERROR: could not parse health report: {raw}", file=sys.stderr)
        raise typer.Exit(code=1)

    rows = [
        ("App Version", report.get("app_version") or "unknown"),
        ("Healthy", report.get("healthy")),
    ]
    for name, status in (report.get("checks") or {}).items():
        rows.append(
            (
                f"Check: {name}",
                "ok" if status.get("healthy") else f"failed ({status.get('error')})",
            )
        )
    metrics = report.get("metrics") or {}
    if metrics:
        rows.append(("Uptime (s)", round(metrics.get("uptime_seconds", 0), 1)))
        rows.append(("Messages Published", metrics.get("messages_published")))
        rows.append(("Messages Received", metrics.get("messages_received")))
        rows.append(("Errors", metrics.get("errors")))

    print_table(["Field", "Value"], rows)


def _enter_raw_repl_with_retries(
    resolved_port: str, command_label: str
) -> DeviceTransport:
    """Open a DeviceTransport and enter raw REPL, retrying the handshake only.

    Enters raw REPL with soft_reset=False: `interrupt()` alone (ctrl-C)
    already lands a running device at a clean idle prompt, so a read-only
    command has no reason to also reboot it. This matters beyond style -
    on firmware whose `main.py` runs an intentionally infinite loop (this
    project's own `PublishService.run()`), a soft-reset (ctrl-D) reboots
    straight back into that loop, which never returns control to print
    the second raw-REPL banner a soft-reset entry waits for, so the
    handshake hangs until timeout every time, not just intermittently.

    Retried in case opening the serial port itself triggers a board
    auto-reset (DTR toggling on connect, common on ESP32 dev boards),
    racing the raw-REPL handshake against that reboot - the same race
    `upload --reset` already retries around.
    """
    last_error: RawReplEntryError | None = None
    for attempt in range(1, UPLOAD_RETRY_ATTEMPTS + 1):
        if attempt > 1:
            print(
                f"NOTE: {command_label} failed (raw-REPL race), retrying "
                f"({attempt}/{UPLOAD_RETRY_ATTEMPTS})...",
                file=sys.stderr,
            )
            time.sleep(UPLOAD_RESET_SETTLE_SECONDS * (attempt - 1))
        transport = DeviceTransport(resolved_port)
        try:
            transport.connect()
            transport.interrupt()
            transport.enter_raw_repl(soft_reset=False)
            return transport
        except RawReplEntryError as exc:
            transport.close()
            last_error = exc
    raise last_error


@contextmanager
def _raw_repl_session(resolved_port: str, command_label: str):
    """Yield a DeviceTransport already in raw REPL; always exits+closes after."""
    transport = _enter_raw_repl_with_retries(resolved_port, command_label)
    try:
        yield transport
    finally:
        transport.exit_raw_repl()
        transport.close()


def _print_raw_repl_failure(resolved_port: str) -> None:
    print(
        f"ERROR: could not enter raw REPL on {resolved_port} after "
        f"{UPLOAD_RETRY_ATTEMPTS} attempts. Firmware may be stuck or "
        "the board may still be rebooting.",
        file=sys.stderr,
    )
    print(
        f"Retry with 'python tinker.py device reset --port {resolved_port}' "
        "and try again.",
        file=sys.stderr,
    )


@device_app.command("ls")
def device_ls(
    port: Optional[str] = typer.Option(
        None, "--port", "-p", help="Serial port of device"
    ),
    path: str = typer.Argument(":", help="Device path to list (default: root)"),
) -> None:
    """List files and folders on the device."""
    config = load_config()
    resolved_port = port or config.get("port")
    if resolved_port is None:
        resolved_port = prompt_for_port()

    try:
        with _raw_repl_session(resolved_port, "device ls") as transport:
            entries = transport.ls(path)
    except RawReplEntryError as exc:
        _print_raw_repl_failure(resolved_port)
        raise typer.Exit(code=1) from exc
    except DeviceExecError as exc:
        print(f"ERROR: {exc.stderr}", file=sys.stderr)
        raise typer.Exit(code=1) from exc

    for name, size, is_dir in entries:
        print("{:12} {}{}".format(size, name, "/" if is_dir else ""))


@device_app.command("test-adapter")
def device_test_adapter(
    module: str = typer.Argument(
        ...,
        help=(
            "Dotted path to an adapter class, e.g. "
            "app.adapters.sensors.dht22.DHT22Adapter"
        ),
    ),
    port: Optional[str] = typer.Option(
        None, "--port", "-p", help="Serial port of device"
    ),
) -> None:
    """Run one adapter's setup()/read()/deinit() cycle on-device."""
    module_path, _, class_name = module.rpartition(".")
    if not module_path:
        print(
            "ERROR: module must be a dotted path to an adapter class, e.g. "
            "app.adapters.sensors.dht22.DHT22Adapter",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)

    config = load_config()
    resolved_port = port or config.get("port")
    if resolved_port is None:
        resolved_port = prompt_for_port()

    script = (
        f"from {module_path} import {class_name}\n"
        f"adapter = {class_name}()\n"
        "adapter.setup()\n"
        "try:\n"
        "    print(adapter.read() if hasattr(adapter, 'read') "
        "else 'no read() method')\n"
        "finally:\n"
        "    adapter.deinit()\n"
    )

    try:
        with _raw_repl_session(resolved_port, "device test-adapter") as transport:
            output = transport.exec(script)
    except RawReplEntryError as exc:
        _print_raw_repl_failure(resolved_port)
        raise typer.Exit(code=1) from exc
    except DeviceExecError as exc:
        print(f"ERROR: {exc.stderr}", file=sys.stderr)
        raise typer.Exit(code=1) from exc

    print(output, end="")


@device_app.command("repl")
def device_repl(
    port: Optional[str] = typer.Option(
        None, "--port", "-p", help="Serial port of device"
    ),
) -> None:
    """Open an interactive REPL session on the device."""
    if shutil.which("mpremote") is None:
        print(
            "ERROR: 'mpremote' not found on PATH. Install it with "
            "'pip install mpremote'.",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)

    config = load_config()
    resolved_port = port or config.get("port")
    if resolved_port is None:
        resolved_port = prompt_for_port()

    cmd = ["mpremote", "connect", resolved_port, "repl"]
    result = _run_mpremote_interactive(cmd, resolved_port)
    if result.returncode != 0:
        raise typer.Exit(code=result.returncode)


def _device_logs(port: Optional[str], capture: Optional[Path]) -> None:
    """Shared implementation for 'device logs' / 'device monitor'.

    mpremote has no read-only tail mode upstream, so this rides the same
    'repl' connection as device_repl; --capture is the one option that
    actually serves the tailing use case (saving the stream to a file).
    """
    if shutil.which("mpremote") is None:
        print(
            "ERROR: 'mpremote' not found on PATH. Install it with "
            "'pip install mpremote'.",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)

    config = load_config()
    resolved_port = port or config.get("port")
    if resolved_port is None:
        resolved_port = prompt_for_port()

    cmd = ["mpremote", "connect", resolved_port, "repl"]
    if capture is not None:
        cmd += ["--capture", str(capture)]
    result = _run_mpremote_interactive(cmd, resolved_port)
    if result.returncode != 0:
        raise typer.Exit(code=result.returncode)


@device_app.command("logs")
def device_logs(
    port: Optional[str] = typer.Option(
        None, "--port", "-p", help="Serial port of device"
    ),
    capture: Optional[Path] = typer.Option(
        None, "--capture", help="Also save the tailed output to this file"
    ),
) -> None:
    """Tail the device's live serial output (Ctrl-] to stop)."""
    _device_logs(port, capture)


@device_app.command("monitor")
def device_monitor(
    port: Optional[str] = typer.Option(
        None, "--port", "-p", help="Serial port of device"
    ),
    capture: Optional[Path] = typer.Option(
        None, "--capture", help="Also save the tailed output to this file"
    ),
) -> None:
    """Alias for 'device logs' — tail the device's live serial output."""
    _device_logs(port, capture)


@device_app.command("tree")
def device_tree(
    port: Optional[str] = typer.Option(
        None, "--port", "-p", help="Serial port of device"
    ),
    path: str = typer.Argument(":", help="Device path to show (default: root)"),
    size: bool = typer.Option(False, "--size", "-s", help="Show file size in bytes"),
    human: bool = typer.Option(
        False, "--human", "-h", help="Show file size in a more human readable way"
    ),
) -> None:
    """Show a tree view of files and folders on the device."""
    config = load_config()
    resolved_port = port or config.get("port")
    if resolved_port is None:
        resolved_port = prompt_for_port()

    remote_path = path[1:] if path.startswith(":") else path
    remote_path = remote_path or "/"

    try:
        with _raw_repl_session(resolved_port, "device tree") as transport:
            print(f":{remote_path}")
            _print_tree(transport, remote_path, size=size, human=human)
    except RawReplEntryError as exc:
        _print_raw_repl_failure(resolved_port)
        raise typer.Exit(code=1) from exc
    except DeviceExecError as exc:
        print(f"ERROR: {exc.stderr}", file=sys.stderr)
        raise typer.Exit(code=1) from exc


_SIZE_UNIT_THRESHOLDS = (
    (1024**4, "T"),
    (1024**3, "G"),
    (1024**2, "M"),
    (1024, "K"),
)


def _human_size(size: int, decimals: int = 1) -> str:
    for threshold, unit in _SIZE_UNIT_THRESHOLDS:
        if size >= threshold:
            return f"{size / threshold:.{decimals}f}{unit}"
    return str(size)


def _print_tree(
    transport: DeviceTransport,
    path: str,
    *,
    size: bool,
    human: bool,
    prefix: str = "",
) -> None:
    """Recursively print a tree, walking one `DeviceTransport.ls()` call per dir.

    There's no raw-REPL primitive for a recursive listing, so this walks
    directories via repeated `ls()` calls and formats the output itself
    (connectors, size columns) on top of the same `ls()` `device ls` uses.
    """
    entries = transport.ls(path)
    for i, (name, entry_size, is_dir) in enumerate(entries):
        connector = "└── " if i == len(entries) - 1 else "├── "
        size_str = ""
        if entry_size > 0 or not is_dir:
            if size:
                size_str = f"[{entry_size:>9}]  "
            elif human:
                size_str = f"[{_human_size(entry_size):>6}]  "
        print(f"{prefix}{connector}{size_str}{name}")
        if is_dir:
            child_path = path.rstrip("/") + "/" + name
            next_prefix = prefix + ("    " if i == len(entries) - 1 else "│   ")
            _print_tree(
                transport, child_path, size=size, human=human, prefix=next_prefix
            )


@device_app.command("rm")
def device_rm(
    port: Optional[str] = typer.Option(
        None, "--port", "-p", help="Serial port of device"
    ),
    path: str = typer.Argument(..., help="Device path to remove"),
    recursive: bool = typer.Option(
        False,
        "--recursive",
        "-r",
        help="Recursively remove a non-empty directory (fs rm --recursive)",
    ),
    dir: bool = typer.Option(
        False, "--dir", "-d", help="Remove an empty directory (fs rmdir)"
    ),
) -> None:
    """Remove a file or directory on the device."""
    config = load_config()
    resolved_port = port or config.get("port")
    if resolved_port is None:
        resolved_port = prompt_for_port()

    try:
        with _raw_repl_session(resolved_port, "device rm") as transport:
            if recursive:
                transport.rm_recursive(path)
            elif dir:
                transport.rmdir(path)
            else:
                transport.rm(path)
    except RawReplEntryError as exc:
        _print_raw_repl_failure(resolved_port)
        raise typer.Exit(code=1) from exc
    except DeviceExecError as exc:
        print(f"ERROR: {exc.stderr}", file=sys.stderr)
        raise typer.Exit(code=1) from exc


@device_app.command("mkdir")
def device_mkdir(
    port: Optional[str] = typer.Option(
        None, "--port", "-p", help="Serial port of device"
    ),
    path: str = typer.Argument(..., help="Device path to create"),
) -> None:
    """Create a directory on the device. A no-op if it already exists."""
    config = load_config()
    resolved_port = port or config.get("port")
    if resolved_port is None:
        resolved_port = prompt_for_port()

    try:
        with _raw_repl_session(resolved_port, "device mkdir") as transport:
            transport.mkdir(path)
    except RawReplEntryError as exc:
        _print_raw_repl_failure(resolved_port)
        raise typer.Exit(code=1) from exc
    except DeviceExecError as exc:
        print(f"ERROR: {exc.stderr}", file=sys.stderr)
        raise typer.Exit(code=1) from exc


@app.command(name="port")
def list_serial_ports() -> None:
    """List available serial ports."""
    ports = sorted(list_ports.comports())
    if not ports:
        print("No serial ports found.")
        raise typer.Exit(code=0)

    rows = [(p.device, p.description if p.description != "n/a" else "") for p in ports]
    print_table(["Port", "Description"], rows)


if __name__ == "__main__":
    app()
