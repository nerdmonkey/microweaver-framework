#!/usr/bin/env python3
"""Build, upload, and manage microweaver firmware."""

import configparser
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

import typer
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
    if shutil.which("esptool") is None:
        print(
            "ERROR: 'esptool' not found on PATH. Install it with "
            "'pip install esptool'.",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)
    cmd = ["esptool", "--port", port_name, "--after", "hard-reset", "chip-id"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(
            f"ERROR: could not reset {port_name}:\n{result.stderr.strip()}",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)


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
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ERROR {src}: {result.stderr.strip()}", file=sys.stderr)
        return False
    print(f"  {src.relative_to(ROOT)} -> {dst.relative_to(ROOT)}")
    return True


@app.command()
def build(
    micropython: str = typer.Option(
        "1.28", help="Target MicroPython version"
    ),
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
    result = subprocess.run(cmd)
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

    cmd = ["mpremote", "connect", resolved_port, "fs", "cp", "-r", ":.", str(path)]
    result = subprocess.run(cmd)
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


@config_app.command("set", no_args_is_help=True)
def config_set(
    port: Optional[str] = typer.Option(None, "--port", "-p", help="Default serial port"),
    baud: Optional[int] = typer.Option(None, "--baud", "-b", help="Default baud rate"),
    path: Optional[Path] = typer.Option(None, "--path", help="Default upload path"),
) -> None:
    """Set default port/baud/path in .microweaver."""
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
