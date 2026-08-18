#!/usr/bin/env python3
"""Build, deploy, and manage microweaver firmware."""

import configparser
import hashlib
import json
import re
import shutil
import ssl
import subprocess  # nosec B404
import sys
import time
import tomllib
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, cast
from urllib.parse import urlparse

import typer
from esptool.cmds import _get_flash_info as get_flash_info
from esptool.cmds import attach_flash, detect_chip, reset_chip
from esptool.logger import log as esptool_log
from esptool.util import FatalError
from serial import SerialException
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
    help="Build, deploy, and manage microweaver firmware.",
)
config_app = typer.Typer(
    no_args_is_help=True, help="View or set default port/baud/path."
)
app.add_typer(config_app, name="config")
device_app = typer.Typer(no_args_is_help=True, help="Interrupt or reset the device.")
app.add_typer(device_app, name="device")
profile_app = typer.Typer(
    no_args_is_help=True,
    help="Create, list, and switch between saved Agnes API connection profiles.",
)
app.add_typer(profile_app, name="profile")
certs_app = typer.Typer(
    no_args_is_help=True, help="Fetch a device's cert bundle from the Agnes API."
)
app.add_typer(certs_app, name="certs")
fleet_app = typer.Typer(no_args_is_help=True, help="Push a build to multiple devices.")
app.add_typer(fleet_app, name="fleet")
ota_app = typer.Typer(
    no_args_is_help=True, help="Build, validate, and compare OTA update manifests."
)
app.add_typer(ota_app, name="ota")
topic_app = typer.Typer(
    no_args_is_help=True, help="List and inspect configured MQTT topics."
)
app.add_typer(topic_app, name="topic")


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


def _profile_section(name: str) -> str:
    return f"profile:{name}"


def list_profiles() -> list[str]:
    """Names of profiles saved under CONFIG_PATH, sorted."""
    if not CONFIG_PATH.exists():
        return []
    cp = configparser.ConfigParser()
    cp.read(CONFIG_PATH)
    return sorted(
        section.split(":", 1)[1]
        for section in cp.sections()
        if section.startswith("profile:")
    )


def load_profile(name: str) -> dict:
    if not CONFIG_PATH.exists():
        return {}
    cp = configparser.ConfigParser()
    cp.read(CONFIG_PATH)
    section = _profile_section(name)
    return dict(cp[section]) if cp.has_section(section) else {}


def save_profile(name: str, **values) -> dict:
    cp = configparser.ConfigParser()
    if CONFIG_PATH.exists():
        cp.read(CONFIG_PATH)
    section = _profile_section(name)
    if not cp.has_section(section):
        cp.add_section(section)
    saved = {}
    for key, value in values.items():
        if value is not None:
            cp.set(section, key, str(value))
            saved[key] = value
    with CONFIG_PATH.open("w") as f:
        cp.write(f)
    return saved


def delete_profile(name: str) -> bool:
    """Remove a saved profile section. Clears the active-profile pointer in
    [default] if it pointed at this profile. Returns whether it existed."""
    if not CONFIG_PATH.exists():
        return False
    cp = configparser.ConfigParser()
    cp.read(CONFIG_PATH)
    removed = cp.remove_section(_profile_section(name))
    if not removed:
        return False
    if (
        cp.has_section("default")
        and cp.get("default", "profile", fallback=None) == name
    ):
        cp.remove_option("default", "profile")
    with CONFIG_PATH.open("w") as f:
        cp.write(f)
    return True


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


def _sha256_file(path: Path) -> str:
    """Return the lowercase hex sha256 digest of a file's contents."""
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


@ota_app.command("build")
def ota_build(
    version: str = typer.Option(
        ..., "--version", help="Release version, e.g. '2.0.0'."
    ),
    base_url: str = typer.Option(
        ...,
        "--base-url",
        help="Base URL the files will be uploaded to, e.g. "
        "'https://cdn.example.com/releases/2.0.0'.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Overwrite an existing dist/ota/<version>/ directory if present.",
    ),
    files: list[Path] = typer.Argument(
        ...,
        help="File paths relative to the project root to include in the release, "
        "e.g. app_main.py app/services/mqtt.py",
    ),
) -> None:
    """Build an OTA manifest.json + payload files under dist/ota/<version>/."""
    version_dir = DIST / "ota" / version
    if version_dir.exists():
        if not force:
            print(
                f"ERROR: {version_dir} already exists. "
                "Remove it or re-run with --force to overwrite.",
                file=sys.stderr,
            )
            raise typer.Exit(code=1)
        shutil.rmtree(version_dir)

    base = base_url.rstrip("/")
    manifest_files: dict[str, dict[str, str]] = {}
    errors = 0

    for rel in files:
        src = ROOT / rel
        if not src.is_file():
            print(f"ERROR: {rel} not found or not a regular file.", file=sys.stderr)
            errors += 1
            continue

        posix_rel = rel.as_posix()
        try:
            sha256 = _sha256_file(src)
        except OSError as exc:
            print(f"ERROR: could not read {rel}: {exc}", file=sys.stderr)
            errors += 1
            continue

        dst = version_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

        manifest_files[posix_rel] = {"url": f"{base}/{posix_rel}", "sha256": sha256}
        print(f"  {posix_rel} -> {dst}")

    if errors:
        shutil.rmtree(version_dir, ignore_errors=True)
        print(f"\n{errors} file(s) failed; no output written.", file=sys.stderr)
        raise typer.Exit(code=1)

    manifest = {"version": version, "files": manifest_files}
    manifest_path = version_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    print(f"\nDone. {len(manifest_files)} file(s), version {version}.")
    print(f"Output: {version_dir}")
    print_table(
        ["File", "SHA256"], [(k, v["sha256"]) for k, v in manifest_files.items()]
    )


_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def _validate_manifest_file_entry(
    key: str, entry, files_root: Optional[Path]
) -> list[str]:
    """Check a single manifest files[] entry, returning any issue strings."""
    if not isinstance(entry, dict):
        return [
            f"{key}: entry is not the {{url, sha256}} object form "
            "(short string-only form is not allowed)"
        ]

    issues = []
    url = entry.get("url")
    if not url or not isinstance(url, str):
        issues.append(f"{key}: missing or invalid 'url'")

    sha256 = entry.get("sha256")
    if not sha256 or not isinstance(sha256, str) or not _SHA256_RE.match(sha256):
        issues.append(f"{key}: missing or malformed 'sha256' (expected 64 hex chars)")
        return issues

    if files_root is not None:
        local = files_root / key
        if not local.is_file():
            issues.append(f"{key}: file not found under --files-root ({local})")
        else:
            actual = _sha256_file(local)
            if actual.lower() != sha256.lower():
                issues.append(
                    f"{key}: checksum mismatch (manifest={sha256}, actual={actual})"
                )
    return issues


def _validate_manifest_structure(manifest) -> tuple[list[str], Optional[str], dict]:
    """Check top-level manifest shape, returning (issues, version, files_field)."""
    issues = []

    version = manifest.get("version") if isinstance(manifest, dict) else None
    if not isinstance(version, str) or not version:
        issues.append("'version' is missing or not a non-empty string")

    files_field = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(files_field, dict) or not files_field:
        issues.append("'files' is missing, not an object, or empty")
        files_field = {}

    return issues, version, files_field


@ota_app.command("validate")
def ota_validate(
    manifest_path: Path = typer.Argument(
        ..., help="Path to a manifest.json to validate."
    ),
    files_root: Optional[Path] = typer.Option(
        None,
        "--files-root",
        help="If given, recompute and compare each file's sha256 against "
        "<files-root>/<key> (in addition to structural checks).",
    ),
) -> None:
    """Validate an OTA manifest.json's structure and (optionally) checksums."""
    try:
        raw = manifest_path.read_text()
    except OSError as exc:
        print(f"ERROR: could not read {manifest_path}: {exc}", file=sys.stderr)
        raise typer.Exit(code=1)

    try:
        manifest = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"ERROR: invalid JSON: {exc}", file=sys.stderr)
        raise typer.Exit(code=1)

    issues, version, files_field = _validate_manifest_structure(manifest)
    for key, entry in files_field.items():
        issues.extend(_validate_manifest_file_entry(key, entry, files_root))

    if issues:
        for issue in issues:
            print(f"ERROR: {issue}", file=sys.stderr)
        print(f"\n{len(issues)} issue(s) found.", file=sys.stderr)
        raise typer.Exit(code=1)

    print(f"manifest OK: version {version}, {len(files_field)} file(s).")


def _load_manifest_for_diff(path: Path) -> tuple[Optional[dict], list[str]]:
    """Read and structurally validate a manifest used by ``ota diff``."""
    try:
        raw = path.read_text()
    except OSError as exc:
        return None, [f"could not read {path}: {exc}"]

    try:
        manifest = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, [f"invalid JSON in {path}: {exc}"]

    issues, _, files_field = _validate_manifest_structure(manifest)
    for key, entry in files_field.items():
        issues.extend(_validate_manifest_file_entry(key, entry, None))
    return manifest, issues


def _diff_manifests(old_manifest: dict, new_manifest: dict) -> dict:
    """Return a stable, JSON-serializable semantic diff of two manifests."""
    old_files = old_manifest["files"]
    new_files = new_manifest["files"]
    old_paths = set(old_files)
    new_paths = set(new_files)

    added = [
        {"path": path, "new": new_files[path]} for path in sorted(new_paths - old_paths)
    ]
    removed = [
        {"path": path, "old": old_files[path]} for path in sorted(old_paths - new_paths)
    ]
    content_changed = []
    url_changed = []

    for path in sorted(old_paths & new_paths):
        old_entry = old_files[path]
        new_entry = new_files[path]
        if old_entry["sha256"].lower() != new_entry["sha256"].lower():
            content_changed.append({"path": path, "old": old_entry, "new": new_entry})
        elif old_entry["url"] != new_entry["url"]:
            url_changed.append({"path": path, "old": old_entry, "new": new_entry})

    old_version = old_manifest["version"]
    new_version = new_manifest["version"]
    version_changed = old_version != new_version
    different = bool(
        version_changed or added or removed or content_changed or url_changed
    )
    return {
        "old_version": old_version,
        "new_version": new_version,
        "version_changed": version_changed,
        "added": added,
        "removed": removed,
        "content_changed": content_changed,
        "url_changed": url_changed,
        "different": different,
    }


@ota_app.command("diff")
def ota_diff(
    old_manifest_path: Path = typer.Argument(
        ..., metavar="OLD_MANIFEST", help="Manifest to use as the comparison base."
    ),
    new_manifest_path: Path = typer.Argument(
        ..., metavar="NEW_MANIFEST", help="Manifest containing the proposed update."
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Print the machine-readable diff as JSON."
    ),
) -> None:
    """Compare two OTA manifests by version, file checksum, and URL."""
    old_manifest, old_issues = _load_manifest_for_diff(old_manifest_path)
    new_manifest, new_issues = _load_manifest_for_diff(new_manifest_path)

    for label, issues in (("OLD", old_issues), ("NEW", new_issues)):
        for issue in issues:
            print(f"ERROR: {label}: {issue}", file=sys.stderr)
    if old_issues or new_issues:
        raise typer.Exit(code=2)

    diff = _diff_manifests(cast(dict, old_manifest), cast(dict, new_manifest))
    if json_output:
        print(json.dumps(diff, indent=2))
    else:
        print(f"OTA manifest diff: {old_manifest_path} -> {new_manifest_path}")
        if diff["version_changed"]:
            print(f"Version: {diff['old_version']} -> {diff['new_version']}")
        else:
            print(f"Version: {diff['old_version']} (unchanged)")

        rows = []
        for status, key in (
            ("ADDED", "added"),
            ("REMOVED", "removed"),
            ("CONTENT", "content_changed"),
            ("URL", "url_changed"),
        ):
            rows.extend((status, item["path"]) for item in diff[key])
        if rows:
            print()
            print_table(["Change", "File"], rows)
        elif not diff["version_changed"]:
            print("No differences.")

    if diff["different"]:
        raise typer.Exit(code=1)


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
def deploy(
    port: Optional[str] = typer.Option(
        None, "--port", "-p", help="Serial port of device (see 'tinker.py port')"
    ),
    baud: Optional[int] = typer.Option(None, "--baud", "-b", help="Baud rate"),
    reset: bool = typer.Option(
        False,
        "--reset",
        help=(
            "Hard-reset the device before deploying. Use this if the device "
            "is stuck (e.g. raw REPL entry fails after several retries)."
        ),
    ),
    path: Optional[Path] = typer.Argument(
        None, help="Local file/folder to deploy (default: ./dist)"
    ),
) -> None:
    """Deploy compiled firmware to a device over serial."""
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
            f"NOTE: deploy ignores --baud (requested {resolved_baud}), "
            "connection always runs at 115200.",
            file=sys.stderr,
        )

    _upload_path(resolved_port, resolved_path, reset, "deploy")

    save_config(port=port, baud=baud, path=path)
    print(f"\nDeployed {resolved_path} -> {resolved_port}")


@app.command()
def restore(
    port: Optional[str] = typer.Option(
        None, "--port", "-p", help="Serial port of device (see 'tinker.py port')"
    ),
    baud: Optional[int] = typer.Option(None, "--baud", "-b", help="Baud rate"),
    reset: bool = typer.Option(
        False, "--reset", help="Hard-reset the device before restoring"
    ),
    path: Path = typer.Argument(
        BACKUP, help="Local backup folder to restore (default: ./backup)"
    ),
) -> None:
    """Deploy a previous `backup` folder's contents back onto the device."""
    # Resolution order: CLI flag > .microweaver > hardcoded default. Unlike
    # deploy, the restore source is always BACKUP unless overridden - it
    # never reads or writes .microweaver's "path" default, so it can't
    # clobber deploy's own default path.
    config = load_config()
    resolved_port = port or config.get("port")
    resolved_baud = baud if baud is not None else int(config.get("baud", DEFAULT_BAUD))

    if resolved_port is None:
        resolved_port = prompt_for_port()
        port = resolved_port

    if not path.exists():
        print(f"ERROR: {path} does not exist.", file=sys.stderr)
        raise typer.Exit(code=1)

    if resolved_baud != 115200:
        print(
            f"NOTE: restore ignores --baud (requested {resolved_baud}), "
            "connection always runs at 115200.",
            file=sys.stderr,
        )

    _upload_path(resolved_port, path, reset, "restore")

    save_config(port=port, baud=baud)
    print(f"\nRestored {path} -> {resolved_port}")


def _upload_path(
    resolved_port: str, resolved_path: Path, reset: bool, command_label: str
) -> None:
    """Push a local file/folder to the device over raw REPL; shared with restore()."""
    if reset:
        print(f"Resetting {resolved_port}...")
        hard_reset(resolved_port)
        time.sleep(UPLOAD_RESET_SETTLE_SECONDS)

    try:
        with _raw_repl_session(resolved_port, command_label) as transport:
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
def backup(
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
    """Back up the device's filesystem to a local folder."""
    # Resolution order: CLI flag > .microweaver > hardcoded default.
    config = load_config()
    resolved_port = port or config.get("port")
    resolved_baud = baud if baud is not None else int(config.get("baud", DEFAULT_BAUD))

    if resolved_port is None:
        resolved_port = prompt_for_port()
        port = resolved_port

    # DeviceTransport always runs at 115200 baud; --baud is accepted for
    # interface/config-file compatibility but has no effect on the transfer.
    if resolved_baud != 115200:
        print(
            f"NOTE: backup ignores --baud (requested {resolved_baud}), "
            "connection always runs at 115200.",
            file=sys.stderr,
        )

    path.mkdir(parents=True, exist_ok=True)

    # get_dir has no include/exclude filter, so if the destination is (or
    # contains) the project root, guard our own config file from being
    # clobbered by whatever the backup pulls in.
    guard_path = path / CONFIG_PATH.name
    guard_backup = guard_path.read_bytes() if guard_path.exists() else None

    try:
        with _raw_repl_session(resolved_port, "backup") as transport:
            transport.get_dir(":", path, on_file=_print_download_file)
    except RawReplEntryError as exc:
        _print_raw_repl_failure(resolved_port)
        raise typer.Exit(code=1) from exc
    except DeviceExecError as exc:
        print(f"ERROR: {exc.stderr}", file=sys.stderr)
        raise typer.Exit(code=1) from exc
    finally:
        if guard_backup is not None:
            guard_path.write_bytes(guard_backup)

    save_config(port=port, baud=baud)
    print(f"\nBacked up {resolved_port} -> {path}")


def _print_download_file(
    remote: str, local: Path, index: int | None = None, total: int | None = None
) -> None:
    prefix = f"[{index}/{total}] " if index is not None else ""
    print(f"{prefix}{remote} -> {local}")


API_KEY_HEADER = "X-API-Key"


class ProvisionApiError(Exception):
    """Raised when the Agnes API rejects or fails a device-provision request."""


def _agnes_api_request(
    request: urllib.request.Request, ca_cert: Optional[Path]
) -> dict:
    """Run an already-built Agnes API request and return its decoded JSON
    response, wrapping any HTTP/URL failure as ProvisionApiError. request's
    url is operator-supplied (--api-url/.microweaver config), not untrusted
    input; https gets a verified ssl context."""
    context = None
    if urlparse(request.full_url).scheme == "https":
        context = ssl.create_default_context(cafile=str(ca_cert) if ca_cert else None)
    try:
        with urllib.request.urlopen(  # nosec B310
            request, context=context, timeout=30
        ) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        try:
            detail = json.loads(detail).get("detail", detail)
        except json.JSONDecodeError:
            pass
        raise ProvisionApiError(f"{exc.code} {exc.reason}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ProvisionApiError(str(exc.reason)) from exc


def _post_agnes_api(
    url: str, api_key: str, ca_cert: Optional[Path], body: dict
) -> dict:
    """POST body as JSON to url with the Agnes X-API-Key header and return
    the decoded JSON response."""
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        method="POST",
        headers={"Content-Type": "application/json", API_KEY_HEADER: api_key},
    )
    return _agnes_api_request(request, ca_cert)


def _get_agnes_api(url: str, api_key: str, ca_cert: Optional[Path]) -> dict:
    """GET url with the Agnes X-API-Key header and return the decoded JSON
    response."""
    request = urllib.request.Request(
        url, method="GET", headers={API_KEY_HEADER: api_key}
    )
    return _agnes_api_request(request, ca_cert)


def _provision_device_via_api(
    api_url: str, api_key: str, ca_cert: Optional[Path], name: str
) -> dict:
    """POST {api_url}/devices to register a managed device with Agnes and
    return its one-time MQTT credentials + cert bundle (DeviceProvisionResponse:
    device_id, username, password, certificate, private_key, ca_cert, ...)."""
    return _post_agnes_api(
        f"{api_url.rstrip('/')}/devices", api_key, ca_cert, {"name": name}
    )


def _list_devices_via_api(
    api_url: str, api_key: str, ca_cert: Optional[Path], limit: int = 100
) -> list[dict]:
    """GET {api_url}/devices?limit=... and return its items (each a
    DeviceResponse: id, name, is_online, last_seen_at, ...)."""
    url = f"{api_url.rstrip('/')}/devices?limit={limit}"
    return _get_agnes_api(url, api_key, ca_cert)["items"]


def _renew_device_cert_via_api(
    api_url: str, api_key: str, ca_cert: Optional[Path], device_id: str
) -> dict:
    """POST {api_url}/devices/{device_id}/renew-cert to issue a fresh cert
    bundle for an already-registered device (CertRenewResponse: device_id,
    certificate, private_key, ca_cert, expires_at) - revokes that device's
    previously active certificate. Unlike _provision_device_via_api, this
    doesn't create a new device identity."""
    return _post_agnes_api(
        f"{api_url.rstrip('/')}/devices/{device_id}/renew-cert",
        api_key,
        ca_cert,
        {"validity_days": 365},
    )


def _provision_mqtt_via_api(
    api_url: str, api_key: str, ca_cert: Optional[Path], device_id: str
) -> dict:
    """POST {api_url}/devices/{device_id}/provision-mqtt to rotate an
    already-registered device's MQTT password and return it in plaintext
    (username stays the same; the password hash Agnes stores can't be
    reversed, so rotate-and-return is the only way to recover working
    credentials for a device whose local device_config.json was lost).
    Response: {device_id, username, password, mqtt_provisioned}. The old
    password stops working the moment this succeeds."""
    return _post_agnes_api(
        f"{api_url.rstrip('/')}/devices/{device_id}/provision-mqtt",
        api_key,
        ca_cert,
        {},
    )


HOME_CONFIG_DIR = Path.home() / ".microweaver"


def _profile_ca_cert_path(profile: str) -> Path:
    return HOME_CONFIG_DIR / profile / "ca.pem"


def _fetch_ca_cert(api_url: str) -> str:
    """GET {api_url}/api/ca and return the PEM text.

    No CA is trusted yet at this point - that's exactly what this call
    bootstraps - so the fetch is unverified (trust-on-first-use). Mirrors
    the equivalent flow in the Agnes repo's own tinker.py (`session profile
    fetch-ca`), which uses the same insecure-fetch-once pattern.
    """
    url = f"{api_url.rstrip('/')}/api/ca"
    context = None
    if urlparse(url).scheme == "https":
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    request = urllib.request.Request(url, method="GET")
    try:
        # url is operator-supplied (--api-url); this fetch is deliberately
        # unverified (trust-on-first-use, see docstring above).
        with urllib.request.urlopen(  # nosec B310
            request, context=context, timeout=30
        ) as resp:
            pem = resp.read().decode()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise ProvisionApiError(f"{exc.code} {exc.reason}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ProvisionApiError(str(exc.reason)) from exc
    if "BEGIN CERTIFICATE" not in pem:
        raise ProvisionApiError("response does not look like a PEM certificate")
    return pem


def _fetch_and_save_ca_cert(profile: str, api_url: str) -> Path:
    """Fetch api_url's CA cert (trust-on-first-use, see _fetch_ca_cert) and
    save it to _profile_ca_cert_path(profile). Raises ProvisionApiError."""
    print(f"Fetching CA from {api_url}/api/ca (insecure, trust-on-first-use)...")
    pem = _fetch_ca_cert(api_url)
    ca_path = _profile_ca_cert_path(profile)
    ca_path.parent.mkdir(parents=True, exist_ok=True)
    ca_path.write_text(pem)
    print(f"Saved CA cert -> {ca_path}")
    return ca_path


@app.command("fetch-ca-cert")
def fetch_ca_cert(
    profile: str = typer.Argument(
        ..., help="Profile name - cert saved to ~/.microweaver/<profile>/ca.pem"
    ),
    api_url: Optional[str] = typer.Option(
        None,
        "--api-url",
        help="Agnes API base URL (default: api_url saved in .microweaver)",
    ),
) -> None:
    """Download the Agnes broker's CA cert and save it per-profile under
    ~/.microweaver/, so 'provision --profile <name>' can verify the API's
    TLS without passing --ca-cert on every run.

    Fetched insecurely (trust-on-first-use) since there's no CA to verify
    against yet. Run this once per host over a network you trust, then
    treat the saved ca.pem as the trust anchor from then on. 'profile
    create' already does this automatically when given an --api-url - this
    command is for re-fetching later or for a profile created without one.
    """
    config = load_config()
    resolved_api_url = (
        api_url or load_profile(profile).get("api_url") or config.get("api_url")
    )
    if not resolved_api_url:
        print(
            "ERROR: --api-url required (none saved for this profile or in "
            ".microweaver).",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)

    try:
        _fetch_and_save_ca_cert(profile, resolved_api_url)
    except ProvisionApiError as exc:
        print(f"ERROR: could not fetch CA cert: {exc}", file=sys.stderr)
        raise typer.Exit(code=1)

    save_profile(profile, api_url=resolved_api_url)
    save_config(profile=profile)


# Secret-masked like SECRET_CONFIG_KEYS below, kept separate since profile
# fields are a different, smaller set (api_url/api_key/port/baud/ca_cert).
PROFILE_SECRET_KEYS = {"api_key"}


@profile_app.command("list")
def profile_list() -> None:
    """List saved profiles, marking the active one with '*'."""
    names = list_profiles()
    if not names:
        print("No profiles saved. Create one with 'profile create <name>'.")
        raise typer.Exit(code=0)
    active = load_config().get("profile")
    rows = [(f"* {name}" if name == active else name,) for name in names]
    print_table(["Profile"], rows)


@profile_app.command("show")
def profile_show(
    name: str = typer.Argument(..., help="Profile name"),
    reveal: bool = typer.Option(
        False, "--reveal", help="Show the api_key value in full instead of masked"
    ),
) -> None:
    """Show a saved profile's settings."""
    values = load_profile(name)
    if not values:
        print(f"ERROR: no profile named '{name}'.", file=sys.stderr)
        raise typer.Exit(code=1)
    rows = [
        (
            key,
            "********"
            if key in PROFILE_SECRET_KEYS and value and not reveal
            else value,
        )
        for key, value in values.items()
    ]
    print_table(["Key", "Value"], rows)


def _prompt_profile_fields(given: dict, defaults: dict, header: str) -> None:
    """Fill any None values in `given` (api_url/api_key/port) in place by
    prompting interactively, showing `defaults` (an existing profile's saved
    values, or {} when creating) as the default for a blank Enter. api_key
    is masked - like _prompt_missing_fields's secret handling - so an
    existing secret is never echoed, not even as the prompt's own hint."""
    print(f"{header}\n")

    if given["api_url"] is None:
        existing = defaults.get("api_url", "")
        value = typer.prompt(
            "Agnes API base URL", default=existing, show_default=bool(existing)
        )
        given["api_url"] = value or None

    if given["api_key"] is None:
        existing = defaults.get("api_key", "")
        if existing:
            typed = typer.prompt(
                "Agnes API key [unchanged]",
                default="",
                show_default=False,
                hide_input=True,
            )
            given["api_key"] = existing if typed == "" else typed
        else:
            value = typer.prompt(
                "Agnes API key", default="", show_default=False, hide_input=True
            )
            given["api_key"] = value or None

    if given["port"] is None:
        existing = defaults.get("port", "")
        value = typer.prompt(
            "Serial port", default=existing, show_default=bool(existing)
        )
        given["port"] = value or None


def _prompt_for_profile_name() -> str:
    if not sys.stdin.isatty():
        print("ERROR: no TTY to prompt for: name.", file=sys.stderr)
        raise typer.Exit(code=1)
    name = typer.prompt("Profile name")
    if not name:
        print("ERROR: profile name cannot be blank.", file=sys.stderr)
        raise typer.Exit(code=1)
    return name


def _fetch_ca_cert_for_new_profile(name: str, api_url: str) -> None:
    """Best-effort CA-cert fetch right after 'profile create' - a failure
    only warns since the profile itself is already saved by this point."""
    try:
        _fetch_and_save_ca_cert(name, api_url)
    except ProvisionApiError as exc:
        print(
            f"WARNING: could not fetch CA cert: {exc}. Retry later with "
            f"'fetch-ca-cert {name} --api-url {api_url}'.",
            file=sys.stderr,
        )


@profile_app.command("create")
def profile_create(
    name: Optional[str] = typer.Argument(None, help="Profile name"),
    api_url: Optional[str] = typer.Option(None, "--api-url", help="Agnes API base URL"),
    api_key: Optional[str] = typer.Option(None, "--api-key", help="Agnes API key"),
    port: Optional[str] = typer.Option(
        None, "--port", "-p", help="Default serial port for this profile"
    ),
    baud: Optional[int] = typer.Option(
        None, "--baud", "-b", help="Default baud rate for this profile"
    ),
    activate: bool = typer.Option(
        True,
        "--activate/--no-activate",
        help="Make this the active profile (default: yes)",
    ),
) -> None:
    """Create a new profile. Fails if one already exists with this name -
    use 'profile edit' to change an existing one instead. Prompts for name
    (if omitted) and any of api_url/api_key/port left unset when run
    interactively.

    When api_url ends up set (flag, prompt, or otherwise), also fetches its
    CA cert (trust-on-first-use, see 'fetch-ca-cert') and saves it to
    ~/.microweaver/<name>/ca.pem. A fetch failure only warns - the profile
    itself is already saved by that point - so it can be retried later with
    'fetch-ca-cert'.
    """
    if name is None:
        name = _prompt_for_profile_name()
    if name in list_profiles():
        print(
            f"ERROR: profile '{name}' already exists. Use 'profile edit' to "
            "change it.",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)
    if sys.stdin.isatty() and (api_url is None or api_key is None or port is None):
        given = {"api_url": api_url, "api_key": api_key, "port": port}
        _prompt_profile_fields(
            given, {}, "Creating profile. Press Enter to leave a field unset."
        )
        api_url, api_key, port = given["api_url"], given["api_key"], given["port"]
    saved = save_profile(name, api_url=api_url, api_key=api_key, port=port, baud=baud)
    if activate:
        save_config(profile=name)
    if saved:
        print_table(["Key", "Value"], saved.items())
    else:
        print(f"Created empty profile '{name}'.")
    suffix = " (active)" if activate else ""
    print(f"\nSaved to {CONFIG_PATH.relative_to(ROOT)}{suffix}")

    if api_url:
        _fetch_ca_cert_for_new_profile(name, api_url)


@profile_app.command("edit")
def profile_edit(
    name: Optional[str] = typer.Argument(None, help="Profile name"),
    api_url: Optional[str] = typer.Option(None, "--api-url", help="Agnes API base URL"),
    api_key: Optional[str] = typer.Option(None, "--api-key", help="Agnes API key"),
    port: Optional[str] = typer.Option(
        None, "--port", "-p", help="Default serial port for this profile"
    ),
    baud: Optional[int] = typer.Option(
        None, "--baud", "-b", help="Default baud rate for this profile"
    ),
) -> None:
    """Update fields on an existing profile. Prompts for name (if omitted)
    and any of api_url/api_key/port left unset when run interactively."""
    if name is None:
        name = _prompt_for_profile_name()
    if name not in list_profiles():
        print(
            f"ERROR: no profile named '{name}'. Use 'profile create' first.",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)
    if sys.stdin.isatty() and (api_url is None or api_key is None or port is None):
        given = {"api_url": api_url, "api_key": api_key, "port": port}
        _prompt_profile_fields(
            given,
            load_profile(name),
            "Editing profile. Press Enter to keep the current value.",
        )
        api_url, api_key, port = given["api_url"], given["api_key"], given["port"]
    saved = save_profile(name, api_url=api_url, api_key=api_key, port=port, baud=baud)
    if not saved:
        print(
            "Nothing to set. Pass --api-url/--api-key/--port/--baud.",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)
    print_table(["Key", "Value"], saved.items())
    print(f"\nSaved to {CONFIG_PATH.relative_to(ROOT)}")


@profile_app.command("delete")
def profile_delete(
    name: str = typer.Argument(..., help="Profile name"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt"),
) -> None:
    """Delete a saved profile. Does not remove its cached CA cert under
    ~/.microweaver/<name>/ - re-run 'fetch-ca-cert' if you recreate it."""
    if name not in list_profiles():
        print(f"ERROR: no profile named '{name}'.", file=sys.stderr)
        raise typer.Exit(code=1)
    if not yes and not typer.confirm(f"Delete profile '{name}'?"):
        raise typer.Exit(code=0)
    delete_profile(name)
    print(f"Deleted profile '{name}'.")


@profile_app.command("use")
def profile_use(
    name: str = typer.Argument(..., help="Profile name to make active"),
) -> None:
    """Make a saved profile the active one - used by default in 'provision'
    and 'fetch-ca-cert' when --profile isn't passed."""
    if name not in list_profiles():
        print(
            f"ERROR: no profile named '{name}'. Use 'profile create' first.",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)
    save_config(profile=name)
    print(f"Active profile -> {name}")


PROVISION_FIELDS = [
    # (json key, prompt label, default, is_secret)
    ("device_name", "Device name", "", False),
    ("wifi_ssid", "WiFi SSID", "", False),
    ("wifi_password", "WiFi password", "", True),
    ("mqtt_broker", "MQTT broker", "localhost", False),
    ("mqtt_port", "MQTT port", 1883, False),
    ("mqtt_client_id", "MQTT client id", "microweaver", False),
    (
        "mqtt_topic_pub",
        "MQTT publish topic",
        "devices/{mqtt_username}/sensors",
        False,
    ),
    (
        "mqtt_topic_sub",
        "MQTT subscribe topic",
        "devices/{mqtt_username}/commands",
        False,
    ),
    (
        "mqtt_topic_status",
        "MQTT status topic",
        "devices/{mqtt_username}/status",
        False,
    ),
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


def _resolve_topic_placeholder(topic: str, mqtt_username: str) -> str:
    """Substitute a "{mqtt_username}" placeholder (from device_config.json.
    example's default, or a hand-typed value) with the device's actual
    resolved username, so the device_config.json written to disk holds the
    real topic rather than an unresolved template - on-device, config/app.py
    reads it as a literal string with no substitution logic. rstrip cleans
    up the trailing "/" a template like ".../{mqtt_username}" leaves behind
    when mqtt_username is still blank."""
    return topic.replace("{mqtt_username}", mqtt_username or "").rstrip("/")


def _prompt_missing_fields(given: dict, defaults: dict) -> None:
    """Fill any None values in `given` (in place) by prompting interactively."""
    print("Provisioning over serial. Press Enter to accept the default.\n")
    for key, label, fallback, secret in PROVISION_FIELDS:
        if given[key] is not None:
            continue
        default_value = defaults.get(key, fallback)
        if secret and default_value:
            # An existing secret must never be echoed - not even as the
            # prompt's own [default] hint - so show a placeholder and only
            # reveal the real value if the user leaves the line blank.
            typed = typer.prompt(
                f"{label} [unchanged]",
                default="",
                type=str,
                hide_input=True,
                show_default=False,
            )
            given[key] = default_value if typed == "" else typed
        else:
            given[key] = typer.prompt(
                label,
                default=default_value,
                type=int if isinstance(fallback, int) else str,
                hide_input=secret,
            )


def _require_tty_for_missing(missing: list) -> None:
    if missing and not sys.stdin.isatty():
        flags = ", ".join(f"--{key.replace('_', '-')}" for key in missing)
        print(f"ERROR: no TTY to prompt for: {flags}.", file=sys.stderr)
        raise typer.Exit(code=1)


def _resolve_provision_connection_args(port, baud, api_url, api_key, profile, ca_cert):
    """Resolve --port/--baud/--api-url/--api-key/--profile/--ca-cert against
    a saved 'profile <name>' section and .microweaver's [default] section, in
    CLI flag > profile > [default] > hardcoded default order."""
    config = load_config()
    resolved_profile = profile or config.get("profile")
    profile_values = load_profile(resolved_profile) if resolved_profile else {}

    resolved_ca_cert = ca_cert or (
        Path(profile_values["ca_cert"])
        if profile_values.get("ca_cert")
        else Path(config["ca_cert"])
        if config.get("ca_cert")
        else None
    )
    if resolved_ca_cert is None and resolved_profile:
        profile_ca_cert = _profile_ca_cert_path(resolved_profile)
        if profile_ca_cert.exists():
            resolved_ca_cert = profile_ca_cert
    return {
        "port": port or profile_values.get("port") or config.get("port"),
        "baud": (
            baud
            if baud is not None
            else int(profile_values.get("baud", config.get("baud", DEFAULT_BAUD)))
        ),
        "api_url": api_url or profile_values.get("api_url") or config.get("api_url"),
        "api_key": api_key or profile_values.get("api_key") or config.get("api_key"),
        "profile": resolved_profile,
        "ca_cert": resolved_ca_cert,
    }


def _require_ca_cert_for_https(api_url: str, ca_cert: Optional[Path]) -> None:
    if urlparse(api_url).scheme == "https" and not ca_cert:
        print(
            "ERROR: --ca-cert is required to verify a https --api-url.",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)


def _prompt_provision_device_choice(
    resolved_api_url: str, resolved_api_key: str, resolved_ca_cert: Optional[Path]
) -> Optional[tuple[str, str]]:
    """List devices via the API and let the operator pick an existing one
    (to renew its cert) or create a new one instead. Returns the chosen
    device's (id, name) - name comes from the same list response, so
    device_config.json's device_name can default to it instead of
    prompting blank for a device the API already knows the name of - or
    None to create new. Also None, with a warning, if the listing itself
    fails or there are no devices yet, since 'create new' is always a safe
    fallback here (unlike certs_download, which has no fallback path
    without a device id already in hand)."""
    try:
        devices = _list_devices_via_api(
            resolved_api_url, resolved_api_key, resolved_ca_cert
        )
    except ProvisionApiError as exc:
        print(f"NOTE: could not list devices ({exc}) - creating new.", file=sys.stderr)
        return None
    if not devices:
        return None
    device_id = _prompt_device_selection(devices, allow_create=True)
    if device_id is None:
        return None
    device_name = next((d["name"] for d in devices if d["id"] == device_id), "")
    return device_id, device_name


def _resolve_provision_device_identity(
    name, resolved_api_url, resolved_api_key, resolved_ca_cert
):
    """Return (resolved_name, resolved_device_id, resolved_device_name) -
    resolved_device_id is set only when an existing device was picked to
    renew, with resolved_device_name as its Agnes display name (for
    defaulting device_config.json's device_name to it); otherwise
    resolved_name is the name to register a new device with (also usable
    as a device_name default - see _resolve_given_fields) and
    resolved_device_name is None. Prompts for --name (after offering to
    pick an existing device to renew instead, see
    _prompt_provision_device_choice) when name isn't given. Exits the CLI
    if there's no TTY to prompt on."""
    if name is not None:
        return name, None, None
    if not sys.stdin.isatty():
        print("ERROR: no TTY to prompt for: --name.", file=sys.stderr)
        raise typer.Exit(code=1)
    picked = _prompt_provision_device_choice(
        resolved_api_url, resolved_api_key, resolved_ca_cert
    )
    if picked is not None:
        device_id, device_name = picked
        return None, device_id, device_name
    return typer.prompt("Device name"), None, None


def _renew_device_via_api(
    resolved_api_url,
    resolved_api_key,
    resolved_ca_cert,
    resolved_device_id,
    have_local_mqtt_creds,
):
    """Renew resolved_device_id's cert, and - when have_local_mqtt_creds is
    False - also rotate its MQTT password via provision-mqtt to recover
    working credentials (renew-cert itself never reissues them). Returns
    (mqtt_creds, cert_bundle); mqtt_creds is None when rotation was skipped.
    Exits the CLI on either API call's failure."""
    print(
        f"Renewing cert for device '{resolved_device_id}' via " f"{resolved_api_url}..."
    )
    try:
        cert_bundle = _renew_device_cert_via_api(
            resolved_api_url, resolved_api_key, resolved_ca_cert, resolved_device_id
        )
    except ProvisionApiError as exc:
        print(f"ERROR: cert renewal failed: {exc}", file=sys.stderr)
        raise typer.Exit(code=1)

    if have_local_mqtt_creds:
        return None, cert_bundle

    print(
        f"No local MQTT credentials for '{resolved_device_id}' - rotating "
        "password via Agnes (old password stops working now)..."
    )
    try:
        mqtt_creds = _provision_mqtt_via_api(
            resolved_api_url, resolved_api_key, resolved_ca_cert, resolved_device_id
        )
    except ProvisionApiError as exc:
        print(f"ERROR: MQTT credential rotation failed: {exc}", file=sys.stderr)
        raise typer.Exit(code=1)
    return mqtt_creds, cert_bundle


def _maybe_register_or_renew_via_api(
    name, resolved_api_url, resolved_api_key, resolved_ca_cert, have_local_mqtt_creds
):
    """Register a new device, or renew an existing one's cert, with the
    Agnes API when --api-key was given - see _resolve_provision_device_identity
    for how the choice between the two is made. Returns
    (mqtt_api_result, cert_bundle, resolved_device_name):
    - mqtt_api_result has username/password to fill MQTT credentials, and is
      non-None when: a new device was registered (DeviceProvisionResponse,
      also carries "certificate" - see _resolve_given_fields), or an existing
      device was renewed with have_local_mqtt_creds=False (see
      _renew_device_via_api).
    - cert_bundle is whichever response carries the fresh certs (either
      one), or None if no API key was given at all.
    - resolved_device_name is the picked device's existing Agnes name on a
      renew, or the name a new device was registered with - either way a
      sensible device_config.json device_name default (see
      _resolve_given_fields), or None if no API key was given at all.
    Exits the CLI on any resolution/registration/renewal error."""
    if not resolved_api_key:
        return None, None, None
    if not resolved_api_url:
        print(
            "ERROR: --api-key given without --api-url (and none saved "
            "in .microweaver).",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)
    _require_ca_cert_for_https(resolved_api_url, resolved_ca_cert)

    (
        resolved_name,
        resolved_device_id,
        resolved_device_name,
    ) = _resolve_provision_device_identity(
        name, resolved_api_url, resolved_api_key, resolved_ca_cert
    )

    if resolved_device_id is not None:
        mqtt_creds, cert_bundle = _renew_device_via_api(
            resolved_api_url,
            resolved_api_key,
            resolved_ca_cert,
            resolved_device_id,
            have_local_mqtt_creds,
        )
        return mqtt_creds, cert_bundle, resolved_device_name

    print(f"Registering device '{resolved_name}' with {resolved_api_url}...")
    try:
        api_result = _provision_device_via_api(
            resolved_api_url, resolved_api_key, resolved_ca_cert, resolved_name
        )
    except ProvisionApiError as exc:
        print(f"ERROR: device registration failed: {exc}", file=sys.stderr)
        raise typer.Exit(code=1)
    print(f"Registered device_id={api_result['device_id']}")
    if api_result.get("warning"):
        print(f"NOTE: {api_result['warning']}")
    return api_result, api_result, resolved_name


def _resolve_given_fields(
    cli_fields, mqtt_api_result, cert_bundle, resolved_device_name, resolved_api_url
):
    """Build the CLI-given field overrides, filling MQTT identity/credentials
    from the Agnes API when available.

    cert_bundle carries device_id on both register and renew (renew already
    knows which device it's renewing), so mqtt_client_id fills from it either
    way - device_name fills from resolved_device_name the same
    unconditional way (see _maybe_register_or_renew_via_api). mqtt_api_result
    carries username/password either from a fresh registration
    (DeviceProvisionResponse) or a renew-time password rotation
    (provision-mqtt response) - both fill username/password the same way,
    but only the registration response also carries "certificate", which is
    how a fresh device also gets a broker host/port guess: provision-mqtt's
    rotation targets a device that (per _maybe_register_or_renew_via_api)
    has no locally known broker either, but rotation is a renew of an
    existing, already-deployed device, so overwriting its real broker with a
    guess would be wrong - the prompt/local device_config.json default is
    left to supply it instead."""
    given = dict(cli_fields)
    if cert_bundle is not None:
        given["mqtt_client_id"] = given["mqtt_client_id"] or cert_bundle["device_id"]
    if resolved_device_name:
        given["device_name"] = given["device_name"] or resolved_device_name
    if mqtt_api_result is None:
        return given
    if "certificate" in mqtt_api_result:
        # API supplies the broker's identity/credentials; it doesn't return
        # a broker host/port, so derive the host from --api-url and default
        # to the plain dynsec port (1883) - mqtt_ssl stays off, matching the
        # dynsec username/password auth these credentials are for.
        given["mqtt_broker"] = (
            given["mqtt_broker"] or urlparse(resolved_api_url).hostname
        )
        given["mqtt_port"] = given["mqtt_port"] or 1883
    given["mqtt_username"] = given["mqtt_username"] or mqtt_api_result["username"]
    given["mqtt_password"] = given["mqtt_password"] or mqtt_api_result["password"]
    return given


def _write_provisioned_certs(certs_dir: Path, api_result: dict) -> dict[str, Path]:
    """Save an API registration result's cert bundle to certs_dir as
    ca.pem/client.pem/private.pem - the API only returns a device's certs
    once, at registration time, so this is the only chance to keep a local
    copy. Mirrors the Agnes project's own tinker.py cert-bundle layout."""
    paths = {
        "ca_cert": certs_dir / "ca.pem",
        "client_cert": certs_dir / "client.pem",
        "client_key": certs_dir / "private.pem",
    }
    certs_dir.mkdir(parents=True, exist_ok=True)
    paths["ca_cert"].write_text(api_result["ca_cert"])
    paths["client_cert"].write_text(api_result["certificate"])
    paths["client_key"].write_text(api_result["private_key"])
    return paths


@app.command()
def provision(
    device_name: Optional[str] = typer.Option(
        None,
        "--device-name",
        help="Device name written to device_config.json's device_name "
        '(used in every publish envelope\'s "device" field). Defaults to '
        "--name when registering a new device via the API, or to the "
        "existing device's Agnes name when picking one to renew.",
    ),
    wifi_ssid: Optional[str] = typer.Option(None, help="WiFi SSID"),
    wifi_password: Optional[str] = typer.Option(None, help="WiFi password"),
    mqtt_broker: Optional[str] = typer.Option(None, help="MQTT broker host"),
    mqtt_port: Optional[int] = typer.Option(None, help="MQTT broker port"),
    mqtt_client_id: Optional[str] = typer.Option(None, help="MQTT client id"),
    mqtt_topic_pub: Optional[str] = typer.Option(None, help="MQTT publish topic"),
    mqtt_topic_sub: Optional[str] = typer.Option(None, help="MQTT subscribe topic"),
    mqtt_topic_status: Optional[str] = typer.Option(None, help="MQTT status topic"),
    mqtt_username: Optional[str] = typer.Option(None, help="MQTT username"),
    mqtt_password: Optional[str] = typer.Option(None, help="MQTT password"),
    api_url: Optional[str] = typer.Option(
        None,
        "--api-url",
        help="Agnes API base URL (e.g. https://192.168.1.38/backend). When "
        "given (or saved in .microweaver), the device is registered (or an "
        "existing one picked to renew) with Agnes: mqtt_client_id/device_id/"
        "device_cert/device_key are filled in from the API response either "
        "way; mqtt_broker only on a fresh registration. mqtt_username/"
        "mqtt_password fill from registration too, or - on a renew, when no "
        "local device_config.json already has them - by rotating the "
        "device's MQTT password via Agnes (invalidates the old one).",
    ),
    api_key: Optional[str] = typer.Option(
        None,
        "--api-key",
        help="Agnes X-API-Key with devices:write scope. Persisted to "
        ".microweaver once given so later runs don't need it again.",
    ),
    ca_cert: Optional[Path] = typer.Option(
        None,
        "--ca-cert",
        help="CA cert to verify --api-url's TLS. Required when --api-url is "
        "https, unless --profile resolves one via 'fetch-ca-cert'.",
    ),
    profile: Optional[str] = typer.Option(
        None,
        "--profile",
        help="Saved profile name (see 'profile create'/'profile list') to "
        "fill in --port/--baud/--api-url/--api-key/--ca-cert from. Defaults "
        "to the active profile ('profile use'). Any of those flags given "
        "explicitly wins over the profile's value.",
    ),
    name: Optional[str] = typer.Option(
        None,
        "--name",
        help="Device name to register with the Agnes API. When omitted "
        "interactively, existing devices are listed first so you can pick "
        "one to renew instead of registering a new one.",
    ),
    skip_certs: bool = typer.Option(
        False,
        "--skip-certs",
        help="Don't touch cert material at all: omit device_cert/device_key "
        "from device_config.json and skip writing ./certs/, even when "
        "registering/renewing via the API.",
    ),
) -> None:
    """Prompt for WiFi/MQTT settings and write device_config.json.

    Fills in the settings a device needs to connect to WiFi/MQTT, purely on
    the host - it doesn't touch a serial port. Run 'build' then 'deploy' (or
    'watch') afterward to actually push it to a device; provisioning and
    deploying are separate steps; this used to also push over serial, but
    that duplicated 'deploy' and only added a second, provision-specific
    raw-REPL failure mode for no benefit.

    When --api-url/--api-key (or their .microweaver defaults) are set and
    --name is omitted on a TTY, existing devices are listed (Azure-CLI-
    picker style, see 'certs download') so you can either pick one to renew
    its cert, or choose to register a brand new device - device details and
    MQTT credentials then come from the Agnes API instead of being typed in
    by hand. Renewing an existing device also rotates its MQTT password via
    Agnes (invalidating the old one) when neither --mqtt-username/
    --mqtt-password nor an existing local device_config.json already has
    them - Agnes only ever returns a device's password once, so rotation is
    the only way to recover working credentials once the local file is
    lost. Either way the response's cert bundle is also saved to
    ./certs/ca.pem, client.pem, and private.pem (mirroring the Agnes
    project's own tinker.py cert layout) unless --skip-certs is given,
    since the API only returns a device's certs once, at registration/
    renewal time.
    """
    resolved = _resolve_provision_connection_args(
        None, None, api_url, api_key, profile, ca_cert
    )
    resolved_api_url = resolved["api_url"]
    resolved_api_key = resolved["api_key"]
    resolved_profile = resolved["profile"]
    resolved_ca_cert = resolved["ca_cert"]

    cli_fields = {
        "device_name": device_name,
        "wifi_ssid": wifi_ssid,
        "wifi_password": wifi_password,
        "mqtt_broker": mqtt_broker,
        "mqtt_port": mqtt_port,
        "mqtt_client_id": mqtt_client_id,
        "mqtt_topic_pub": mqtt_topic_pub,
        "mqtt_topic_sub": mqtt_topic_sub,
        "mqtt_topic_status": mqtt_topic_status,
        "mqtt_username": mqtt_username,
        "mqtt_password": mqtt_password,
    }
    defaults = _load_provision_defaults()
    have_local_mqtt_creds = bool(
        cli_fields["mqtt_username"] or defaults.get("mqtt_username")
    ) and bool(cli_fields["mqtt_password"] or defaults.get("mqtt_password"))

    (
        mqtt_api_result,
        cert_bundle,
        resolved_device_name,
    ) = _maybe_register_or_renew_via_api(
        name,
        resolved_api_url,
        resolved_api_key,
        resolved_ca_cert,
        have_local_mqtt_creds,
    )

    given = _resolve_given_fields(
        cli_fields, mqtt_api_result, cert_bundle, resolved_device_name, resolved_api_url
    )

    missing = [key for key, value in given.items() if value is None]
    _require_tty_for_missing(missing)

    if missing:
        _prompt_missing_fields(given, defaults)

    config_path = ROOT / "device_config.json"
    merged = dict(defaults)
    merged.update(given)
    merged["mqtt_topic_pub"] = _resolve_topic_placeholder(
        merged["mqtt_topic_pub"], merged["mqtt_username"]
    )
    merged["mqtt_topic_sub"] = _resolve_topic_placeholder(
        merged["mqtt_topic_sub"], merged["mqtt_username"]
    )
    merged["mqtt_topic_status"] = _resolve_topic_placeholder(
        merged["mqtt_topic_status"], merged["mqtt_username"]
    )
    if int(merged["mqtt_port"]) == 8883:
        # 8883 is the TLS listener (matches _resolve_given_fields' own
        # 1883-is-plain-dynsec assumption) - a plaintext connect to it gets
        # ECONNRESET at the TLS handshake, not a clean auth failure, so this
        # is easy to end up debugging as a broker/cert issue instead.
        merged["mqtt_ssl"] = True
    if cert_bundle is not None:
        merged["device_id"] = cert_bundle["device_id"]
        if not skip_certs:
            merged["device_cert"] = cert_bundle["certificate"]
            merged["device_key"] = cert_bundle["private_key"]
            cert_paths = _write_provisioned_certs(ROOT / "certs", cert_bundle)
            print(f"Saved cert bundle -> {cert_paths['ca_cert'].parent}")

    try:
        Setting(config_path=str(config_path)).save(**merged)
    except ConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise typer.Exit(code=1)

    save_config(
        api_url=resolved_api_url if cert_bundle is not None else None,
        api_key=resolved_api_key if cert_bundle is not None else None,
        ca_cert=resolved_ca_cert if cert_bundle is not None else None,
        profile=resolved_profile if cert_bundle is not None else None,
    )
    print(
        f"\nWrote {config_path.name}. Run 'tinker.py build && tinker.py deploy' "
        "to push it to a device."
    )


def _prompt_device_selection(
    devices: list[dict], allow_create: bool = False
) -> Optional[str]:
    """Print a numbered table of devices and prompt for one, Azure-CLI
    picker style. Returns the chosen device's id, or None if allow_create
    and the added 'create new' row (0) was picked instead."""
    rows = [
        (
            index,
            device["id"],
            device["name"],
            "online" if device.get("is_online") else "offline",
            device.get("last_seen_at") or "never",
        )
        for index, device in enumerate(devices, start=1)
    ]
    prompt_text = "Select a device by number"
    low = 1
    if allow_create:
        rows.append(("0", "-", "Create new device", "-", "-"))
        prompt_text += ", or 0 to create new"
        low = 0
    print_table(["#", "Device ID", "Name", "Status", "Last Seen"], rows)
    choice = typer.prompt(prompt_text)
    try:
        index = int(choice)
        if not low <= index <= len(devices):
            raise ValueError
    except ValueError:
        print(
            f"ERROR: '{choice}' is not a valid selection ({low}-{len(devices)}).",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)
    if allow_create and index == 0:
        return None
    return devices[index - 1]["id"]


def _resolve_device_id(
    device_id: Optional[str],
    resolved_api_url: str,
    resolved_api_key: str,
    resolved_ca_cert: Optional[Path],
) -> str:
    """Return device_id as given, or list devices via the API and prompt
    for one (see _prompt_device_selection). Exits the CLI if there's no TTY
    to pick from, the listing fails, or there are no devices to choose."""
    if device_id is not None:
        return device_id
    if not sys.stdin.isatty():
        print("ERROR: no TTY to prompt for: --device-id.", file=sys.stderr)
        raise typer.Exit(code=1)
    try:
        devices = _list_devices_via_api(
            resolved_api_url, resolved_api_key, resolved_ca_cert
        )
    except ProvisionApiError as exc:
        print(f"ERROR: could not list devices: {exc}", file=sys.stderr)
        raise typer.Exit(code=1)
    if not devices:
        print("ERROR: no devices found for this API key.", file=sys.stderr)
        raise typer.Exit(code=1)
    return _prompt_device_selection(devices)


@certs_app.command("download")
def certs_download(
    device_id: Optional[str] = typer.Option(
        None,
        "--device-id",
        help="Existing device's ID (see 'devices list' on the Agnes side) "
        "to renew and download certs for",
    ),
    api_url: Optional[str] = typer.Option(
        None,
        "--api-url",
        help="Agnes API base URL (default: resolved from --profile/.microweaver)",
    ),
    api_key: Optional[str] = typer.Option(
        None,
        "--api-key",
        help="Agnes X-API-Key with devices:write scope (default: resolved "
        "from --profile/.microweaver)",
    ),
    ca_cert: Optional[Path] = typer.Option(
        None,
        "--ca-cert",
        help="CA cert to verify --api-url's TLS. Required when --api-url is "
        "https, unless --profile resolves one via 'fetch-ca-cert'.",
    ),
    profile: Optional[str] = typer.Option(
        None,
        "--profile",
        help="Saved profile name (see 'profile create'/'profile list') to "
        "resolve --api-url/--api-key/--ca-cert from. Defaults to the active "
        "profile ('profile use').",
    ),
    out_dir: Optional[Path] = typer.Option(
        None,
        "--out-dir",
        help="Directory to save ca.pem/client.pem/private.pem into "
        "(default: ./certs)",
    ),
) -> None:
    """Renew an existing device's cert and save the resulting bundle to
    --out-dir. When --device-id is omitted and running interactively, lists
    devices from the Agnes API and prompts for one to pick, Azure-CLI-picker
    style.

    Calls POST /devices/{device_id}/renew-cert - this issues a fresh
    certificate for that device and revokes its previously active one, it
    does not create a new device (see 'provision --api-url' for that). The
    device's old certificate stops working immediately, so push the new
    bundle to it (or re-run 'provision'/'deploy') soon after.
    """
    resolved = _resolve_provision_connection_args(
        None, None, api_url, api_key, profile, ca_cert
    )
    resolved_api_url = resolved["api_url"]
    resolved_api_key = resolved["api_key"]
    resolved_ca_cert = resolved["ca_cert"]

    if not resolved_api_key:
        print(
            "ERROR: --api-key required (none saved for this profile or in "
            ".microweaver).",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)
    if not resolved_api_url:
        print(
            "ERROR: --api-url required (none saved for this profile or in "
            ".microweaver).",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)
    _require_ca_cert_for_https(resolved_api_url, resolved_ca_cert)

    resolved_device_id = _resolve_device_id(
        device_id, resolved_api_url, resolved_api_key, resolved_ca_cert
    )

    print(f"Renewing cert for device '{resolved_device_id}' via {resolved_api_url}...")
    try:
        api_result = _renew_device_cert_via_api(
            resolved_api_url, resolved_api_key, resolved_ca_cert, resolved_device_id
        )
    except ProvisionApiError as exc:
        print(f"ERROR: cert renewal failed: {exc}", file=sys.stderr)
        raise typer.Exit(code=1)

    cert_paths = _write_provisioned_certs(out_dir or (ROOT / "certs"), api_result)
    print(f"Saved cert bundle -> {cert_paths['ca_cert'].parent}")


# Mirrors main.py's publish-adapter wiring (enabled-flag attr, topic-suffix
# attr, display component, purpose). Kept in sync by hand, same as
# PROVISION_FIELDS above -- update this list whenever main.py gains/removes a
# publish adapter.
PUBLISH_TOPIC_SPECS = [
    ("DHT_ENABLED", "DHT_TEMPERATURE_TOPIC_SUFFIX", "dht-temperature", "telemetry"),
    ("DHT_ENABLED", "DHT_HUMIDITY_TOPIC_SUFFIX", "dht-humidity", "telemetry"),
    (
        "POTENTIOMETER_ENABLED",
        "POTENTIOMETER_TOPIC_SUFFIX",
        "potentiometer",
        "telemetry",
    ),
    ("ROTARY_ANGLE_ENABLED", "ROTARY_ANGLE_TOPIC_SUFFIX", "rotary-angle", "telemetry"),
]


# Mirrors main.py's subscribe-adapter wiring (enabled-flag attr, topic-suffix
# attr, display component, purpose).
SUBSCRIBE_TOPIC_SPECS = [
    ("RELAY_ENABLED", "RELAY_TOPIC_SUFFIX", "relay", "command"),
    ("RGB_ENABLED", "RGB_TOPIC_SUFFIX", "rgb", "command"),
    ("OLED_ENABLED", "OLED_TOPIC_SUFFIX", "oled", "command"),
]


# Mirrors main.py's status-topic wiring: only actuators with an is_on() state
# to report get one (not OLED), a subset of SUBSCRIBE_TOPIC_SPECS.
STATUS_TOPIC_SPECS = [
    ("RELAY_ENABLED", "RELAY_TOPIC_SUFFIX", "relay", "state"),
    ("RGB_ENABLED", "RGB_TOPIC_SUFFIX", "rgb", "state"),
]

VALID_TOPIC_PURPOSES = {"telemetry", "command", "state"}


def _topic(base_topics: list, suffix: str) -> str:
    """Mirrors main.py's _topic: base (mqtt_topic_pub/sub, first entry)
    plus the device's own topic suffix."""
    base = base_topics[0] if base_topics else ""
    return f"{base}/{suffix}" if base else suffix


def _build_topic_rows(setting) -> list:
    """Unified PUB+SUB+STATUS row list: (direction, topic, device, component,
    purpose, qos). QoS is a global setting (mqtt_publish_qos) for PUB/STATUS
    rows -- there's no per-topic override in the schema -- and "n/a" for SUB
    rows, since subscribe() never sends a QoS."""
    device = setting.MQTT_CLIENT_ID
    qos = str(setting.MQTT_PUBLISH_QOS)
    pub_base = list(setting.MQTT_TOPIC_PUB)
    sub_base = list(setting.MQTT_TOPIC_SUB)
    status_base = list(setting.MQTT_TOPIC_STATUS)

    rows = []

    pub_rows = [
        (
            "PUB",
            _topic(pub_base, getattr(setting, suffix_attr)),
            device,
            component,
            purpose,
            qos,
        )
        for enabled_attr, suffix_attr, component, purpose in PUBLISH_TOPIC_SPECS
        if getattr(setting, enabled_attr)
    ]
    rows.extend(
        pub_rows
        or [
            ("PUB", topic, device, "(no publish adapters enabled)", "-", qos)
            for topic in pub_base
        ]
    )

    sub_rows = [
        (
            "SUB",
            _topic(sub_base, getattr(setting, suffix_attr)),
            device,
            component,
            purpose,
            "n/a",
        )
        for enabled_attr, suffix_attr, component, purpose in SUBSCRIBE_TOPIC_SPECS
        if getattr(setting, enabled_attr)
    ]
    # Matches main.py: topics = subscribe_topics if subscribe_adapters else []
    # -- with zero subscribe adapters enabled, RuntimeService is handed
    # topics=[] and never subscribes to anything, regardless of mqtt_topic_sub.
    rows.extend(
        sub_rows
        or [
            (
                "SUB",
                "(none - no subscribe adapters enabled)",
                device,
                "main.py overrides mqtt_topic_sub to [] when none enabled",
                "-",
                "n/a",
            )
        ]
    )

    status_rows = [
        (
            "STATUS",
            _topic(status_base, getattr(setting, suffix_attr)),
            device,
            component,
            purpose,
            qos,
        )
        for enabled_attr, suffix_attr, component, purpose in STATUS_TOPIC_SPECS
        if getattr(setting, enabled_attr)
    ]
    rows.extend(
        status_rows
        or [
            (
                "STATUS",
                "(none - no status-reporting adapters enabled)",
                device,
                "n/a",
                "-",
                "n/a",
            )
        ]
    )

    return rows


def _filter_topic_rows(
    rows: list,
    *,
    pub: bool = False,
    sub: bool = False,
    device: Optional[str] = None,
    component: Optional[str] = None,
    purpose: Optional[str] = None,
) -> list:
    if pub:
        rows = [r for r in rows if r[0] == "PUB"]
    if sub:
        rows = [r for r in rows if r[0] == "SUB"]
    if device:
        rows = [r for r in rows if r[2] == device]
    if component:
        rows = [r for r in rows if r[3].lower() == component.lower()]
    if purpose:
        rows = [r for r in rows if r[4].lower() == purpose.lower()]
    return rows


def _build_topic_tree(rows: list) -> dict:
    root: dict = {}
    for direction, topic, _device, component, purpose, _qos in rows:
        segments = [s for s in topic.split("/") if s]
        node = root
        for seg in segments:
            node = node.setdefault(seg, {})
        node.setdefault("_leaves", []).append((direction, component, purpose))
    return root


def _print_topic_tree(node: dict, prefix: str = "") -> None:
    entries = sorted(k for k in node if k != "_leaves")
    for i, key in enumerate(entries):
        connector = "└── " if i == len(entries) - 1 else "├── "
        child = node[key]
        annotation = ""
        if "_leaves" in child:
            labels = ", ".join(
                f"{direction} {component}"
                if purpose == "-"
                else f"{direction} {component} ({purpose})"
                for direction, component, purpose in child["_leaves"]
            )
            annotation = f"  [{labels}]"
        print(f"{prefix}{connector}{key}{annotation}")
        grandchildren = {k: v for k, v in child.items() if k != "_leaves"}
        if grandchildren:
            next_prefix = prefix + ("    " if i == len(entries) - 1 else "│   ")
            _print_topic_tree(grandchildren, next_prefix)


def _load_topics_setting(config_path: Optional[Path]) -> tuple:
    if config_path is None:
        real = ROOT / "device_config.json"
        config_path = real if real.exists() else ROOT / "device_config.json.example"
    if not config_path.exists():
        print(f"ERROR: config file not found: {config_path}", file=sys.stderr)
        raise typer.Exit(code=1)

    try:
        setting = Setting(config_path=str(config_path)).get_settings()
    except ConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise typer.Exit(code=1)

    try:
        source = config_path.relative_to(ROOT)
    except ValueError:
        source = config_path
    return setting, source


@topic_app.command("list")
def topic_list(
    config_path: Optional[Path] = typer.Option(
        None,
        "--config",
        help="Path to device_config.json (default: repo's own, "
        "falling back to device_config.json.example if not provisioned yet)",
    ),
    pub: bool = typer.Option(False, "--pub", help="Show only PUB rows"),
    sub: bool = typer.Option(False, "--sub", help="Show only SUB rows"),
    device: Optional[str] = typer.Option(
        None, "--device", help="Filter by device id (matches mqtt_client_id)"
    ),
    component: Optional[str] = typer.Option(
        None,
        "--component",
        help="Filter by component, e.g. relay, dht-temperature, rotary-angle",
    ),
    purpose: Optional[str] = typer.Option(
        None, "--purpose", help="Filter by purpose: telemetry, command, or state"
    ),
) -> None:
    """List configured MQTT topics: direction, topic, device, component,
    purpose, and QoS."""
    if pub and sub:
        print("ERROR: cannot combine --pub and --sub", file=sys.stderr)
        raise typer.Exit(code=1)
    if purpose and purpose.lower() not in VALID_TOPIC_PURPOSES:
        valid = ", ".join(sorted(VALID_TOPIC_PURPOSES))
        print(f"ERROR: unknown purpose '{purpose}' (valid: {valid})", file=sys.stderr)
        raise typer.Exit(code=1)

    setting, source = _load_topics_setting(config_path)
    print(f"Config source: {source}\n")

    rows = _filter_topic_rows(
        _build_topic_rows(setting),
        pub=pub,
        sub=sub,
        device=device,
        component=component,
        purpose=purpose,
    )
    print_table(["Direction", "Topic", "Device", "Component", "Purpose", "QoS"], rows)


@topic_app.command("tree")
def topic_tree(
    config_path: Optional[Path] = typer.Option(
        None,
        "--config",
        help="Path to device_config.json (default: repo's own, "
        "falling back to device_config.json.example if not provisioned yet)",
    ),
) -> None:
    """Show a hierarchical tree view of configured MQTT topics."""
    setting, source = _load_topics_setting(config_path)
    print(f"Config source: {source}\n")
    print(setting.MQTT_CLIENT_ID or "(unclaimed device)")
    _print_topic_tree(_build_topic_tree(_build_topic_rows(setting)))


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


def _rebuild_and_deploy(
    port: Optional[str],
    baud: Optional[int],
    reset: bool,
    micropython: str,
    march: str,
) -> None:
    """Run build() then deploy() for watch(), skipping deploy if the build failed."""
    print("\nChange detected, rebuilding...")
    try:
        build(micropython=micropython, march=march, no_clean=False)
    except typer.Exit as exc:
        if exc.exit_code:
            print("Build failed, skipping deploy.", file=sys.stderr)
            return

    try:
        deploy(port=port, baud=baud, reset=reset, path=None)
    except typer.Exit as exc:
        if exc.exit_code:
            print("Deploy failed.", file=sys.stderr)


@app.command()
def watch(
    port: Optional[str] = typer.Option(
        None, "--port", "-p", help="Serial port of device (see 'tinker.py port')"
    ),
    baud: Optional[int] = typer.Option(None, "--baud", "-b", help="Baud rate"),
    reset: bool = typer.Option(
        False, "--reset", help="Hard-reset the device before each deploy"
    ),
    micropython: str = typer.Option("1.28", help="Target MicroPython version"),
    march: str = typer.Option(
        "xtensawin", help="Target architecture (default: xtensawin for ESP32)"
    ),
    interval: float = typer.Option(
        1.0, "--interval", help="Polling interval in seconds"
    ),
) -> None:
    """Watch app/, config/, and root source files; rebuild + deploy on change."""
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
            _rebuild_and_deploy(port, baud, reset, micropython, march)
    except KeyboardInterrupt:
        print("\nStopped watching.")


@config_app.command("show")
def config_show(
    reveal: bool = typer.Option(
        False, "--reveal", help="Show the api_key value in full instead of masked"
    ),
) -> None:
    """Print current .microweaver defaults."""
    config = load_config()
    if not config:
        print("No config file found.")
        raise typer.Exit(code=0)
    rows = [
        (key, "********" if key == "api_key" and value and not reveal else value)
        for key, value in config.items()
    ]
    print_table(["Key", "Value"], rows)


@config_app.command("set")
def config_set(
    port: Optional[str] = typer.Option(
        None, "--port", "-p", help="Default serial port"
    ),
    baud: Optional[int] = typer.Option(None, "--baud", "-b", help="Default baud rate"),
    path: Optional[Path] = typer.Option(None, "--path", help="Default deploy path"),
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


# Keys whose values are masked in `device config` output unless --reveal is
# passed, mirroring PROVISION_FIELDS' is_secret flag plus device_key (a
# private key, never prompted for so it isn't in PROVISION_FIELDS at all).
SECRET_CONFIG_KEYS = {
    "wifi_password",
    "mqtt_password",
    "device_key",
    "provisioning_ap_password",
}


def _format_config_value(key: str, value, reveal: bool):
    if not reveal and key in SECRET_CONFIG_KEYS and value:
        return "********"
    return value


@device_app.command("config")
def device_config(
    config_path: Optional[Path] = typer.Option(
        None,
        "--config",
        help="Path to device_config.json (default: repo's own, "
        "falling back to device_config.json.example if not provisioned yet)",
    ),
    reveal: bool = typer.Option(
        False, "--reveal", help="Show secret values in full instead of masked"
    ),
) -> None:
    """Show device_config.json contents as a table, Azure CLI-style."""
    if config_path is None:
        real = ROOT / "device_config.json"
        config_path = real if real.exists() else ROOT / "device_config.json.example"
    if not config_path.exists():
        print(f"ERROR: config file not found: {config_path}", file=sys.stderr)
        raise typer.Exit(code=1)

    try:
        with config_path.open() as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: could not read {config_path}: {exc}", file=sys.stderr)
        raise typer.Exit(code=1)

    try:
        source = config_path.relative_to(ROOT)
    except ValueError:
        source = config_path
    print(f"Config source: {source}\n")

    rows = [
        (key, _format_config_value(key, value, reveal)) for key, value in raw.items()
    ]
    print_table(["Key", "Value"], rows)


# Device name -> device_config.json enable flag. Mirrors SUBSCRIBE_ADAPTER_FLAGS
# / PUBLISH_ADAPTER_FLAGS above plus the dht_enabled special case, but keyed by
# json field name (not Setting attribute name) since Setting.save() writes
# json keys directly.
DEVICE_ENABLE_FLAGS = [
    ("dht", "dht_enabled"),
    ("relay", "relay_enabled"),
    ("rgb", "rgb_enabled"),
    ("oled", "oled_enabled"),
    ("potentiometer", "potentiometer_enabled"),
    ("rotary", "rotary_angle_enabled"),
]
DEVICE_ENABLE_FLAG_MAP = dict(DEVICE_ENABLE_FLAGS)


def _set_device_flags(names: str, config_path: Optional[Path], enabled: bool) -> None:
    requested = [name.strip().lower() for name in names.split(",") if name.strip()]
    if not requested:
        print("ERROR: no device names given", file=sys.stderr)
        raise typer.Exit(code=1)

    unknown = [name for name in requested if name not in DEVICE_ENABLE_FLAG_MAP]
    if unknown:
        valid = ", ".join(name for name, _ in DEVICE_ENABLE_FLAGS)
        print(
            f"ERROR: unknown device(s): {', '.join(unknown)} (valid: {valid})",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)

    if config_path is None:
        config_path = ROOT / "device_config.json"
    if not config_path.exists():
        print(
            f"ERROR: config file not found: {config_path} "
            "(run `tinker.py device provision` first)",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)

    updates = {DEVICE_ENABLE_FLAG_MAP[name]: enabled for name in requested}
    try:
        Setting(config_path=str(config_path)).save(**updates)
    except ConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise typer.Exit(code=1)

    state = "enabled" if enabled else "disabled"
    for name in requested:
        print(
            f"{state}: {name} ({DEVICE_ENABLE_FLAG_MAP[name]}={str(enabled).lower()})"
        )


@device_app.command("enable")
def device_enable(
    names: str = typer.Argument(
        ...,
        help="Comma-separated device names: dht,relay,rgb,oled,potentiometer,rotary",
    ),
    config_path: Optional[Path] = typer.Option(
        None,
        "--config",
        help="Path to device_config.json (default: repo's own)",
    ),
) -> None:
    """Enable one or more device adapters (sets *_enabled to true)."""
    _set_device_flags(names, config_path, True)


@device_app.command("disable")
def device_disable(
    names: str = typer.Argument(
        ...,
        help="Comma-separated device names: dht,relay,rgb,oled,potentiometer,rotary",
    ),
    config_path: Optional[Path] = typer.Option(
        None,
        "--config",
        help="Path to device_config.json (default: repo's own)",
    ),
) -> None:
    """Disable one or more device adapters (sets *_enabled to false)."""
    _set_device_flags(names, config_path, False)


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
    `deploy --reset` already retries around.
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
    try:
        transport = _enter_raw_repl_with_retries(resolved_port, command_label)
    except SerialException as exc:
        typer.secho(
            f"ERROR: Serial port '{resolved_port}' could not be opened.",
            fg=typer.colors.RED,
            err=True,
        )
        typer.echo(
            "The device may be disconnected, its port may have changed, or another "
            "process may be using it.",
            err=True,
        )
        typer.echo(err=True)
        typer.echo("Try this:", err=True)
        typer.secho(
            "  python tinker.py port",
            fg=typer.colors.CYAN,
            err=True,
        )
        typer.echo("Then retry with '--port <port>'.", err=True)
        raise typer.Exit(code=1) from exc
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
