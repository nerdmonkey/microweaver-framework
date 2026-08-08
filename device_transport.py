"""Minimal raw-REPL transport for scripted, non-interactive device operations.

Replaces per-command `mpremote connect ...` subprocess calls with a single
held serial connection driven through the MicroPython raw REPL protocol:
open -> interrupt -> enter raw REPL -> batch operations -> exit raw REPL ->
close. See docs/tinker.md for the operations that still shell out to the
`mpremote` CLI (interactive REPL, log tailing) rather than using this class.
"""

import os
import time
from pathlib import Path
from typing import Callable

import serial

RAW_REPL_PROMPT = b"raw REPL; CTRL-B to exit\r\n>"
RAW_REPL_BANNER = b"raw REPL; CTRL-B to exit\r\n"
SOFT_REBOOT_MARKER = b"soft reboot\r\n"
EOF_MARKER = b"\x04"


class DeviceTransportError(Exception):
    """Base class for DeviceTransport failures."""


class RawReplEntryError(DeviceTransportError):
    """Board didn't answer the raw-REPL handshake (stuck/rebooting firmware)."""


class DeviceExecError(DeviceTransportError):
    """Remote code raised an exception; carries the on-device traceback text."""

    def __init__(self, stdout: str, stderr: str):
        super().__init__(stderr)
        self.stdout = stdout
        self.stderr = stderr


class DeviceTransport:
    """Raw-REPL serial connection to one MicroPython device.

    Wraps exactly one pyserial connection and drives it through the raw
    REPL protocol for scripted, non-interactive batch operations.
    """

    def __init__(self, port: str, baudrate: int = 115200, timeout: float = 10.0):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self._serial = None
        self._in_raw_repl = False

    def __enter__(self) -> "DeviceTransport":
        self.connect()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def connect(self) -> None:
        self._serial = serial.Serial(
            self.port, baudrate=self.baudrate, timeout=self.timeout
        )

    def close(self) -> None:
        if self._serial is not None:
            self._serial.close()
            self._serial = None
        self._in_raw_repl = False

    def interrupt(self) -> None:
        self._serial.write(b"\r\x03")  # ctrl-C: interrupt any running program
        self._flush_input()

    def enter_raw_repl(self, soft_reset: bool = True) -> None:
        self._serial.write(b"\r\x01")  # ctrl-A: enter raw REPL

        if soft_reset:
            data = self._read_until(RAW_REPL_PROMPT)
            if not data.endswith(RAW_REPL_PROMPT):
                raise RawReplEntryError(f"could not enter raw repl: {data!r}")

            self._serial.write(EOF_MARKER)  # ctrl-D: soft reset
            data = self._read_until(SOFT_REBOOT_MARKER)
            if not data.endswith(SOFT_REBOOT_MARKER):
                raise RawReplEntryError(f"could not enter raw repl: {data!r}")

        data = self._read_until(RAW_REPL_BANNER)
        if not data.endswith(RAW_REPL_BANNER):
            raise RawReplEntryError(f"could not enter raw repl: {data!r}")

        self._in_raw_repl = True

    def exit_raw_repl(self) -> None:
        self._serial.write(b"\r\x02")  # ctrl-B: enter friendly REPL
        self._in_raw_repl = False

    def exec(self, code: str, timeout: float | None = None) -> str:
        data = self._read_until(b">")
        if not data.endswith(b">"):
            raise RawReplEntryError(f"no raw repl prompt: {data!r}")

        command_bytes = code.encode("utf-8")
        chunk_size = 256
        for i in range(0, len(command_bytes), chunk_size):
            end = i + chunk_size
            chunk = command_bytes[i:end]
            self._serial.write(chunk)
            time.sleep(0.01)
        self._serial.write(EOF_MARKER)

        ack = self._serial.read(2)
        if ack != b"OK":
            raise DeviceExecError("", f"could not exec command (response: {ack!r})")

        stdout = self._read_until(EOF_MARKER, timeout=timeout)
        if not stdout.endswith(EOF_MARKER):
            raise DeviceExecError("", "timeout waiting for exec output")
        stdout = stdout[:-1]

        stderr = self._read_until(EOF_MARKER, timeout=timeout)
        if not stderr.endswith(EOF_MARKER):
            raise DeviceExecError(stdout.decode(), "timeout waiting for exec error")
        stderr = stderr[:-1]

        if stderr:
            raise DeviceExecError(stdout.decode(), stderr.decode())

        return stdout.decode()

    def ls(self, path: str = ":") -> list[tuple[str, int, bool]]:
        """List (name, size, is_dir) entries for one remote directory."""
        remote_path = self._strip_colon(path) or "/"
        script = (
            "import os\n"
            f"for _n in sorted(os.listdir({remote_path!r})):\n"
            f"    _p = {remote_path!r}.rstrip('/') + '/' + _n\n"
            "    _st = os.stat(_p)\n"
            "    print(_st[6], bool(_st[0] & 0x4000), _n)\n"
        )
        output = self.exec(script)
        entries = []
        for line in output.splitlines():
            if not line:
                continue
            size_str, is_dir_str, name = line.split(" ", 2)
            entries.append((name, int(size_str), is_dir_str == "True"))
        return entries

    def mkdir(self, path: str) -> None:
        """Create a remote directory. Idempotent: a no-op if it already exists."""
        remote_path = self._strip_colon(path)
        self.exec(
            "import os\n"
            "try:\n"
            f"    os.mkdir({remote_path!r})\n"
            "except OSError as e:\n"
            "    if e.args[0] != 17:\n"
            "        raise\n"
        )

    def put_file(
        self,
        local: Path,
        remote: str,
        chunk_size: int = 256,
        on_start: Callable[[Path, str], None] | None = None,
    ) -> None:
        """Write a local file to the device, chunk_size raw bytes per exec() call.

        `on_start`, if given, is called once with (local, remote) before any
        bytes are sent - lets a caller print progress for slow transfers.
        """
        remote_path = self._strip_colon(remote)
        if on_start is not None:
            on_start(Path(local), remote_path)
        self.exec(f"f = open({remote_path!r}, 'wb')\nw = f.write")
        with open(local, "rb") as fh:
            while True:
                chunk = fh.read(chunk_size)
                if not chunk:
                    break
                self.exec(f"w({chunk!r})")
        self.exec("f.close()")

    def put_dir(
        self,
        local: Path,
        remote: str = ":",
        on_file: Callable[[Path, str, int, int], None] | None = None,
    ) -> None:
        """Upload a local directory's contents into a remote directory.

        The contents of `local` land directly under `remote`, not inside a
        new subfolder named after `local`. `on_file`, if given, is called
        once per file as (local, remote, index, total) before that file
        starts uploading.
        """
        remote_root = self._strip_colon(remote) or "/"
        local = Path(local)
        file_pairs = []
        for dirpath, _dirnames, filenames in os.walk(local):
            rel = Path(dirpath).relative_to(local)
            if rel == Path("."):
                remote_dir = remote_root
            else:
                remote_dir = remote_root.rstrip("/") + "/" + rel.as_posix()
                self.mkdir(remote_dir)
            for filename in sorted(filenames):
                local_file = Path(dirpath) / filename
                remote_file = remote_dir.rstrip("/") + "/" + filename
                file_pairs.append((local_file, remote_file))

        total = len(file_pairs)
        for index, (local_file, remote_file) in enumerate(file_pairs, start=1):
            if on_file is not None:
                on_file(local_file, remote_file, index, total)
            self.put_file(local_file, remote_file)

    @staticmethod
    def _strip_colon(path: str) -> str:
        return path[1:] if path.startswith(":") else path

    def _flush_input(self) -> None:
        while self._serial.in_waiting > 0:
            self._serial.read(self._serial.in_waiting)

    def _read_until(self, ending: bytes, timeout: float | None = None) -> bytes:
        deadline_timeout = self.timeout if timeout is None else timeout
        data = b""
        begin = time.monotonic()
        while not data.endswith(ending):
            if self._serial.in_waiting > 0:
                data += self._serial.read(1)
            elif time.monotonic() - begin >= deadline_timeout:
                break
            else:
                time.sleep(0.01)
        return data
