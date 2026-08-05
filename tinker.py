#!/usr/bin/env python3
"""Compile firmware .py files to .mpy bytecode in dist/."""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
DIST = ROOT / "dist"

PACKAGE_DIRS = ["app", "config"]
ROOT_FILES_COMPILE = ["_boot.py", "main.py"]
ROOT_FILES_COPY = ["boot.py"]


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


def main():
    parser = argparse.ArgumentParser(
        description="Compile microweaver firmware to .mpy bytecode in dist/"
    )
    parser.add_argument(
        "--micropython",
        default="1.28",
        help="Target MicroPython version (default: 1.28)",
    )
    parser.add_argument(
        "--march",
        default="xtensawin",
        help="Target architecture (default: xtensawin for ESP32)",
    )
    parser.add_argument(
        "--no-clean",
        action="store_true",
        help="Skip removing dist/ before building",
    )
    args = parser.parse_args()

    if not args.no_clean and DIST.exists():
        shutil.rmtree(DIST)
        print("Cleaned dist/")

    errors = 0

    for pkg in PACKAGE_DIRS:
        for src in sorted((ROOT / pkg).rglob("*.py")):
            dst = DIST / src.relative_to(ROOT).with_suffix(".mpy")
            if not compile_file(src, dst, args.micropython, args.march):
                errors += 1

    for name in ROOT_FILES_COMPILE:
        src = ROOT / name
        dst = DIST / src.with_suffix(".mpy").name
        if not compile_file(src, dst, args.micropython, args.march):
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
        sys.exit(1)
    print("\nDone. Output: dist/")


if __name__ == "__main__":
    main()
