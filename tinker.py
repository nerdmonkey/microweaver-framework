#!/usr/bin/env python3
"""Build, upload, and manage microweaver firmware."""

import shutil
import subprocess
import sys
from pathlib import Path

import typer
from serial.tools import list_ports

ROOT = Path(__file__).parent
DIST = ROOT / "dist"

PACKAGE_DIRS = ["app", "config"]
ROOT_FILES_COMPILE = ["_boot.py", "main.py"]
ROOT_FILES_COPY = ["boot.py"]

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="Build, upload, and manage microweaver firmware.",
)


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


@app.command(no_args_is_help=True)
def upload(
    port: str = typer.Option(
        ..., "--port", "-p", help="Serial port of device (see 'tinker.py port')"
    ),
    baud: int = typer.Option(115200, "--baud", "-b", help="Baud rate"),
    path: Path = typer.Argument(
        DIST,
        help="Local file/folder to upload (default: ./dist)",
        exists=True,
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

    # mpremote's CLI hardcodes 115200 baud (no override flag exists upstream
    # as of 1.28.0); --baud is accepted for interface parity but has no
    # effect on the actual transfer today.
    if baud != 115200:
        print(
            f"NOTE: mpremote ignores --baud (requested {baud}), "
            "connection always runs at 115200.",
            file=sys.stderr,
        )

    src = f"{path}/." if path.is_dir() else str(path)
    cmd = ["mpremote", "connect", port, "fs", "cp", "-r", src, ":"]
    result = subprocess.run(cmd)
    if result.returncode != 0:
        raise typer.Exit(code=result.returncode)
    print(f"\nUploaded {path} -> {port}")


@app.command(name="port")
def list_serial_ports() -> None:
    """List available serial ports."""
    ports = sorted(list_ports.comports())
    if not ports:
        print("No serial ports found.")
        raise typer.Exit(code=0)

    for p in ports:
        desc = p.description if p.description != "n/a" else ""
        print(f"  {p.device}  {desc}")


if __name__ == "__main__":
    app()
