#!/usr/bin/env python3
"""Build, upload, and manage microweaver firmware."""

import configparser
import shutil
import subprocess  # nosec B404
import sys
from pathlib import Path
from typing import Optional

import typer
from esptool.cmds import _get_flash_info as get_flash_info
from esptool.cmds import attach_flash, detect_chip, reset_chip
from esptool.logger import log as esptool_log
from esptool.util import FatalError
from serial.tools import list_ports

ROOT = Path(__file__).parent
DIST = ROOT / "dist"
BACKUP = ROOT / "backup"
CONFIG_PATH = ROOT / ".microweaver"
DEFAULT_BAUD = 115200

PACKAGE_DIRS = ["app", "config"]
ROOT_FILES_COMPILE = ["_boot.py", "main.py"]
ROOT_FILES_COPY = ["boot.py"]

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="Build, upload, and manage microweaver firmware.",
)
config_app = typer.Typer(
    no_args_is_help=True, help="View or set default port/baud/path."
)
app.add_typer(config_app, name="config")
device_app = typer.Typer(no_args_is_help=True, help="Interrupt or reset the device.")
app.add_typer(device_app, name="device")


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
    if not no_clean and DIST.exists():
        shutil.rmtree(DIST)
        print("Cleaned dist/")

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
            "is stuck (e.g. mpremote fails with 'could not enter raw repl')."
        ),
    ),
    path: Optional[Path] = typer.Argument(
        None, help="Local file/folder to upload (default: ./dist)"
    ),
) -> None:
    """Upload compiled firmware to a device over serial."""
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
    resolved_path = path or (Path(config["path"]) if "path" in config else DIST)

    if resolved_port is None:
        resolved_port = prompt_for_port()
        port = resolved_port

    if not resolved_path.exists():
        print(f"ERROR: {resolved_path} does not exist.", file=sys.stderr)
        raise typer.Exit(code=1)

    # mpremote's CLI hardcodes 115200 baud (no override flag exists upstream
    # as of 1.28.0); --baud is accepted for interface parity but has no
    # effect on the actual transfer today.
    if resolved_baud != 115200:
        print(
            f"NOTE: mpremote ignores --baud (requested {resolved_baud}), "
            "connection always runs at 115200.",
            file=sys.stderr,
        )

    if reset:
        print(f"Resetting {resolved_port}...")
        hard_reset(resolved_port)

    src = f"{resolved_path}/." if resolved_path.is_dir() else str(resolved_path)
    cmd = ["mpremote", "connect", resolved_port, "fs", "cp", "-r", src, ":"]
    result = subprocess.run(cmd)  # nosec B603
    if result.returncode != 0:
        raise typer.Exit(code=result.returncode)

    save_config(port=port, baud=baud, path=path)
    print(f"\nUploaded {resolved_path} -> {resolved_port}")


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
    result = subprocess.run(cmd)  # nosec B603

    if guard_backup is not None:
        guard_path.write_bytes(guard_backup)

    if result.returncode != 0:
        raise typer.Exit(code=result.returncode)

    save_config(port=port, baud=baud)
    print(f"\nDownloaded {resolved_port} -> {path}")


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


def _mpremote_field(resolved_port: str, script: str) -> str:
    """Run `script` on-device via `mpremote exec` and return its last output line.

    Used for opportunistic `device info` rows: any print output before the
    final line (e.g. a service's own startup logging) is discarded.
    """
    try:
        result = subprocess.run(  # nosec B603 B607
            ["mpremote", "connect", resolved_port, "exec", script],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip().splitlines()[-1]
        return "unavailable (device unresponsive)"
    except subprocess.TimeoutExpired:
        return "unavailable (timed out, device may be busy)"


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

    if shutil.which("mpremote") is not None:
        rows.append(
            (
                "MicroPython",
                _mpremote_field(resolved_port, "import os; print(os.uname())"),
            )
        )
        rows.append(
            (
                "Reset Reason",
                _mpremote_field(
                    resolved_port,
                    "from app.services.reset import ResetService; "
                    "print(ResetService().read())",
                ),
            )
        )

    if not rows:
        print("No device details could be read.")
        raise typer.Exit(code=1)

    print_table(["Field", "Value"], rows)


@device_app.command("ls")
def device_ls(
    port: Optional[str] = typer.Option(
        None, "--port", "-p", help="Serial port of device"
    ),
    path: str = typer.Argument(":", help="Device path to list (default: root)"),
) -> None:
    """List files and folders on the device."""
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

    cmd = ["mpremote", "connect", resolved_port, "fs", "ls", path]
    result = subprocess.run(cmd)  # nosec B603
    if result.returncode != 0:
        raise typer.Exit(code=result.returncode)


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
    result = subprocess.run(cmd)  # nosec B603
    if result.returncode != 0:
        raise typer.Exit(code=result.returncode)


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

    cmd = ["mpremote", "connect", resolved_port, "fs"]
    if size:
        cmd.append("--size")
    if human:
        cmd.append("--human")
    cmd += ["tree", path]
    result = subprocess.run(cmd)  # nosec B603
    if result.returncode != 0:
        raise typer.Exit(code=result.returncode)


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

    cmd = ["mpremote", "connect", resolved_port, "fs"]
    if recursive:
        cmd.append("--recursive")
        cmd += ["rm", path]
    elif dir:
        cmd += ["rmdir", path]
    else:
        cmd += ["rm", path]
    result = subprocess.run(cmd)  # nosec B603
    if result.returncode != 0:
        raise typer.Exit(code=result.returncode)


@device_app.command("mkdir")
def device_mkdir(
    port: Optional[str] = typer.Option(
        None, "--port", "-p", help="Serial port of device"
    ),
    path: str = typer.Argument(..., help="Device path to create"),
) -> None:
    """Create a directory on the device."""
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

    cmd = ["mpremote", "connect", resolved_port, "fs", "mkdir", path]
    result = subprocess.run(cmd)  # nosec B603
    if result.returncode != 0:
        raise typer.Exit(code=result.returncode)


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
