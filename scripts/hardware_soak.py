#!/usr/bin/env python3
"""Run the destructive ESP32 release-gate checks for issue #177.

The runner keeps credentials inside a mode-0700 temporary backup, restores the
device after every destructive phase, and writes a secret-free JSON report.
Provisioning still requires a human to join the SoftAP and submit the form;
everything that can be verified over serial is checked automatically.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import serial

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from device_transport import (  # noqa: E402
    DeviceTransport,
    DeviceTransportError,
    RawReplEntryError,
)

PROVISION_CONFIRMATION = "PROVISION"
WATCHDOG_MAIN = """import time
import machine

_watchdog = None


def start():
    global _watchdog
    print("SOAK: watchdog probe started")
    _watchdog = machine.WDT(timeout=2000)
    while True:
        time.sleep_ms(250)


def start_safe_mode():
    print("SOAK: safe mode reached")
    while True:
        print("SOAK: safe mode alive")
        time.sleep(1)
"""


class SoakFailure(RuntimeError):
    """A release-gate phase failed its hardware assertion."""


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        while chunk := source.read(8192):
            digest.update(chunk)
    return digest.hexdigest()


@contextmanager
def raw_repl_session(port, attempts=4):
    """Open a non-resetting raw-REPL session, retrying handshake races."""
    last_error = None
    transport = None
    for attempt in range(1, attempts + 1):
        transport = DeviceTransport(port)
        try:
            transport.connect()
            transport.interrupt()
            transport.enter_raw_repl(soft_reset=False)
            break
        except (DeviceTransportError, serial.SerialException) as exc:
            last_error = exc
            transport.close()
            if attempt < attempts:
                time.sleep(1)
    else:
        raise RawReplEntryError(
            f"could not enter raw REPL on {port} after {attempts} attempts"
        ) from last_error

    try:
        yield transport
    finally:
        try:
            transport.exit_raw_repl()
        except Exception:
            pass
        transport.close()


class HardwareSoak:
    def __init__(
        self,
        port,
        artifacts,
        stages,
        manifest_url=None,
        ota_target=None,
        watch_seconds=20,
        burn_in_hours=24,
        input_fn=input,
        command_runner=subprocess.run,
        serial_cls=serial.Serial,
    ):
        self.port = port
        self.artifacts = Path(artifacts).resolve()
        self.backup = self.artifacts / ".device-backup"
        self.stages = stages
        self.manifest_url = manifest_url
        self.ota_target = ota_target
        self.watch_seconds = watch_seconds
        self.burn_in_hours = burn_in_hours
        self.input = input_fn
        self.command_runner = command_runner
        self.serial_cls = serial_cls
        self.restored = False
        self.artifacts_created = False
        self.ota_attempted = False
        self.watchdog_probe_installed = False
        self.report = {
            "issue": 177,
            "started_at": utc_now(),
            "port": port,
            "commit": self._git_commit(),
            "stages": {},
            "result": "running",
        }

    def _git_commit(self):
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        return result.stdout.strip() or "unknown"

    def _record(self, stage, result, **details):
        self.report["stages"][stage] = {
            "result": result,
            "recorded_at": utc_now(),
            **details,
        }
        self._write_report()

    def _write_report(self):
        self.artifacts.mkdir(parents=True, exist_ok=True)
        os.chmod(self.artifacts, 0o700)
        report_path = self.artifacts / "report.json"
        report_path.write_text(json.dumps(self.report, indent=2) + "\n")
        os.chmod(report_path, 0o600)

    def _tinker(self, *args, log_name=None):
        command = [sys.executable, str(REPO_ROOT / "tinker.py"), *map(str, args)]
        result = self.command_runner(
            command,
            cwd=REPO_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        output = result.stdout or ""
        if output:
            print(output, end="" if output.endswith("\n") else "\n")
        if log_name:
            log_path = self.artifacts / log_name
            log_path.write_text(output)
            os.chmod(log_path, 0o600)
        if result.returncode != 0:
            raise SoakFailure(f"tinker.py {' '.join(map(str, args))} failed")
        return output

    def prepare(self):
        if not Path(self.port).exists():
            raise SoakFailure(f"serial port does not exist: {self.port}")
        self.artifacts.mkdir(parents=True, exist_ok=False)
        self.artifacts_created = True
        os.chmod(self.artifacts, 0o700)
        self._write_report()
        self._tinker("backup", "--port", self.port, self.backup, log_name="backup.log")
        os.chmod(self.backup, 0o700)
        self._tinker("device", "info", "--port", self.port, log_name="device-info.log")
        self._record("prepare", "passed")

    def restore(self):
        self._tinker("device", "reset", "--port", self.port)
        cleanup_error = None
        try:
            self._cleanup_transients()
        except Exception as exc:
            cleanup_error = exc
        self._tinker(
            "restore", "--port", self.port, self.backup, log_name="restore.log"
        )
        self._tinker("device", "reset", "--port", self.port)
        if cleanup_error:
            raise SoakFailure(
                "temporary soak files could not be removed"
            ) from cleanup_error
        self.restored = True

    def _cleanup_transients(self):
        with raw_repl_session(self.port) as transport:
            paths = ["boot_state.json"]
            if self.watchdog_probe_installed:
                paths.extend(["main.py", "main.soak_bak"])
            if self.ota_attempted:
                paths.append("soak_ota_state.json")
                paths.append(self.ota_target + ".ota_new")
                paths.append(self.ota_target + ".ota_bak")
            for path in paths:
                transport.exec(
                    "import os\n"
                    "try:\n"
                    f"    os.remove({path!r})\n"
                    "except OSError:\n"
                    "    pass\n"
                )

    def provisioning(self):
        print("\nFresh provisioning will temporarily remove device_config.json.")
        answer = self.input(f"Type {PROVISION_CONFIRMATION} to continue: ").strip()
        if answer != PROVISION_CONFIRMATION:
            raise SoakFailure("fresh provisioning was not confirmed")

        self._tinker("device", "rm", "--port", self.port, "device_config.json")
        self._tinker("device", "reset", "--port", self.port)
        print(
            "Join Microweaver-Setup, open http://192.168.4.1, submit real WiFi "
            "credentials, and wait for 'Credentials saved. Connected!'."
        )
        self.input("Press Enter after that message appears: ")

        with raw_repl_session(self.port) as transport:
            output = transport.exec(
                "try:\n"
                "    try:\n"
                "        import ujson as json\n"
                "    except ImportError:\n"
                "        import json\n"
                "    with open('device_config.json', 'r') as config_file:\n"
                "        config = json.load(config_file)\n"
                "    print('SOAK_CONFIG_FILE', True)\n"
                "    print('SOAK_WIFI_SET', bool(config.get('wifi_ssid')))\n"
                "except Exception as error:\n"
                "    print('SOAK_CONFIG_FILE', False)\n"
                "    print('SOAK_CONFIG_ERROR', type(error).__name__)\n"
            )
        if "SOAK_CONFIG_FILE True" not in output:
            detail = output.strip().splitlines()[-1] if output.strip() else "no output"
            raise SoakFailure("provisioning config verification failed: " + detail)
        if "SOAK_WIFI_SET True" not in output:
            raise SoakFailure("provisioning saved an empty WiFi SSID")
        self._record("provisioning", "passed", wifi_credentials_persisted=True)
        self.restore()

    def ota(self):
        if not self.manifest_url or not self.ota_target:
            raise SoakFailure("OTA requires --ota-manifest-url and --ota-target")
        if self.ota_target.lstrip("/") == "device_config.json":
            raise SoakFailure("device_config.json cannot be used as the OTA target")
        self.ota_attempted = True

        before_path = self.artifacts / "ota-target-before.bin"
        after_path = self.artifacts / "ota-target-after.bin"
        restored_path = self.artifacts / "ota-target-restored.bin"
        state_path = "soak_ota_state.json"

        with raw_repl_session(self.port) as transport:
            transport.get_file(self.ota_target, before_path)
            output = transport.exec(
                "from app.services.ota import OtaService\n"
                "from config.app import Setting\n"
                "s = Setting().get_settings()\n"
                f"o = OtaService({self.manifest_url!r}, setting=s, "
                f"state_path={state_path!r})\n"
                "print('SOAK_OTA_APPLIED', o.apply_update())\n",
                timeout=120,
            )
            if "SOAK_OTA_APPLIED True" not in output:
                raise SoakFailure("the real HTTP OTA did not apply")
            exists = transport.exec(
                "import os\n"
                "def _e(p):\n"
                "    try:\n"
                "        os.stat(p); return True\n"
                "    except OSError:\n"
                "        return False\n"
                f"print('SOAK_OTA_STATE', _e({state_path!r}))\n"
                f"print('SOAK_OTA_BACKUP', _e({(self.ota_target + '.ota_bak')!r}))\n"
            )
            if "SOAK_OTA_STATE True" not in exists:
                raise SoakFailure("OTA state was not persisted")
            if "SOAK_OTA_BACKUP True" not in exists:
                raise SoakFailure("OTA target was not backed up before the swap")
            transport.get_file(self.ota_target, after_path)
            rollback = transport.exec(
                "from app.services.ota import OtaService\n"
                "from config.app import Setting\n"
                "s = Setting().get_settings()\n"
                f"o = OtaService(setting=s, state_path={state_path!r})\n"
                "print('SOAK_OTA_ROLLED_BACK', o.rollback())\n"
            )
            if "SOAK_OTA_ROLLED_BACK True" not in rollback:
                raise SoakFailure("OTA rollback did not run")
            transport.get_file(self.ota_target, restored_path)

        before_hash = sha256(before_path)
        after_hash = sha256(after_path)
        restored_hash = sha256(restored_path)
        if before_hash == after_hash:
            raise SoakFailure("OTA target did not change after apply")
        if before_hash != restored_hash:
            raise SoakFailure("OTA rollback did not restore the original bytes")
        self._record(
            "ota",
            "passed",
            target=self.ota_target,
            before_sha256=before_hash,
            applied_sha256=after_hash,
            restored_sha256=restored_hash,
        )

    def recovery(self):
        probe = self.artifacts / "watchdog_main.py"
        probe.write_text(WATCHDOG_MAIN)
        os.chmod(probe, 0o600)

        with raw_repl_session(self.port) as transport:
            transport.exec(
                "import os\n"
                "from config.app import Setting\n"
                "s = Setting().get_settings()\n"
                "s.save(boot_loop_protection_enabled=True, "
                "boot_loop_max_attempts=2, boot_interrupt_window_seconds=1, "
                "ota_enabled=False)\n"
                "try:\n"
                "    os.remove('boot_state.json')\n"
                "except OSError:\n"
                "    pass\n"
                "try:\n"
                "    os.rename('main.mpy', 'main.soak_bak')\n"
                "except OSError:\n"
                "    pass\n"
            )
            transport.put_file(probe, "main.py")
            self.watchdog_probe_installed = True

        self._tinker("device", "reset", "--port", self.port)
        log_path = self.artifacts / "watchdog-recovery.log"
        deadline = time.monotonic() + self.watch_seconds
        chunks = []
        with self.serial_cls(self.port, baudrate=115200, timeout=0.25) as stream:
            while time.monotonic() < deadline:
                chunk = stream.read(stream.in_waiting or 1)
                if chunk:
                    chunks.append(chunk)
        output = b"".join(chunks).decode("utf-8", errors="replace")
        log_path.write_text(output)
        os.chmod(log_path, 0o600)
        print(output)
        if "SOAK: safe mode reached" not in output:
            raise SoakFailure("watchdog resets did not reach safe mode")
        if '"reason": "watchdog"' not in output:
            raise SoakFailure("watchdog reset reason was not observed")
        self._record(
            "recovery",
            "passed",
            watchdog_reset_observed=True,
            safe_mode_observed=True,
        )

    def burn_in(self):
        self._tinker("device", "reset", "--port", self.port)
        log_path = self.artifacts / "burn-in.log"
        deadline = time.monotonic() + (self.burn_in_hours * 3600)
        reset_events = 0
        bytes_captured = 0
        with self.serial_cls(self.port, baudrate=115200, timeout=0.25) as stream:
            with open(log_path, "wb") as log:
                while time.monotonic() < deadline:
                    chunk = stream.read(stream.in_waiting or 1)
                    if not chunk:
                        continue
                    log.write(chunk)
                    log.flush()
                    bytes_captured += len(chunk)
                    reset_events += chunk.count(b'"event": "reset"')
        os.chmod(log_path, 0o600)
        if not bytes_captured:
            raise SoakFailure("burn-in captured no device serial output")
        self._record(
            "burnin",
            "passed",
            duration_hours=self.burn_in_hours,
            bytes_captured=bytes_captured,
            reset_events_observed=reset_events,
        )

    def run(self):
        os.umask(0o077)
        failure = None
        try:
            self.prepare()
            if "provisioning" in self.stages:
                self.provisioning()
            if "ota" in self.stages:
                self.ota()
            if "recovery" in self.stages:
                self.recovery()
            if "burnin" in self.stages:
                if "recovery" in self.stages:
                    self.restore()
                self.burn_in()
            self.report["result"] = "passed"
        except Exception as exc:
            failure = exc
            self.report["result"] = "failed"
            self.report["failure"] = str(exc)
        finally:
            if self.backup.exists():
                try:
                    self.restore()
                    self.report["restored"] = True
                    shutil.rmtree(self.backup)
                except Exception as restore_error:
                    self.report["restored"] = False
                    self.report["restore_failure"] = str(restore_error)
                    failure = failure or restore_error
            self.report["finished_at"] = utc_now()
            if self.artifacts_created:
                self._write_report()

        if failure:
            raise SoakFailure(str(failure)) from failure
        return self.report


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Run the issue #177 ESP32 provisioning/OTA/recovery soak"
    )
    parser.add_argument("--port", required=True, help="ESP32 serial port")
    parser.add_argument(
        "--artifacts",
        type=Path,
        default=Path("hardware-soak-results")
        / datetime.now().strftime("%Y%m%d-%H%M%S"),
        help="New directory for secret-free evidence (must not already exist)",
    )
    parser.add_argument(
        "--stages",
        default="provisioning,ota,recovery",
        help="Comma-separated subset of provisioning,ota,recovery,burnin",
    )
    parser.add_argument(
        "--ota-manifest-url",
        help="Real HTTP(S) manifest URL used by the on-device OTA service",
    )
    parser.add_argument(
        "--ota-target",
        help="Existing device file updated by the manifest and verified on rollback",
    )
    parser.add_argument(
        "--watch-seconds",
        type=int,
        default=20,
        help="Seconds to capture watchdog and boot-loop serial evidence",
    )
    parser.add_argument(
        "--burn-in-hours",
        type=float,
        default=24,
        help="Duration of the burnin stage (default: 24 hours)",
    )
    args = parser.parse_args(argv)
    args.stages = {stage.strip() for stage in args.stages.split(",") if stage.strip()}
    unknown = args.stages - {"provisioning", "ota", "recovery", "burnin"}
    if unknown:
        parser.error("unknown stages: " + ", ".join(sorted(unknown)))
    return args


def main(argv=None):
    args = parse_args(argv)
    soak = HardwareSoak(
        port=args.port,
        artifacts=args.artifacts,
        stages=args.stages,
        manifest_url=args.ota_manifest_url,
        ota_target=args.ota_target,
        watch_seconds=args.watch_seconds,
        burn_in_hours=args.burn_in_hours,
    )
    try:
        report = soak.run()
    except SoakFailure as exc:
        print(f"HARDWARE SOAK FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"HARDWARE SOAK PASSED: {soak.artifacts / 'report.json'}")
    return 0 if report["result"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
