import itertools

import pytest

import device_transport
from device_transport import DeviceExecError, DeviceTransport, RawReplEntryError


class FakeSerial:
    """Byte-buffer stand-in for pyserial's Serial, driven by pre-fed responses."""

    def __init__(self, script: bytes = b""):
        self._buffer = bytearray(script)
        self.written = []
        self.closed = False

    @property
    def in_waiting(self):
        return len(self._buffer)

    def read(self, n=1):
        n = min(n, len(self._buffer))
        data = bytes(self._buffer[:n])
        del self._buffer[:n]
        return data

    def write(self, data):
        self.written.append(data)
        return len(data)

    def close(self):
        self.closed = True


def make_device_transport(serial_double=None, port="/dev/ttyFAKE", **kwargs):
    transport = DeviceTransport(port=port, **kwargs)
    if serial_double is not None:
        transport._serial = serial_double
    return transport


# --------------------------------------------------------------------------
# connect / close
# --------------------------------------------------------------------------


def test_connect_opens_serial(mocker):
    fake = FakeSerial()
    mock_serial_cls = mocker.patch.object(
        device_transport.serial, "Serial", return_value=fake
    )
    transport = make_device_transport(port="/dev/ttyUSB0", baudrate=115200, timeout=5)

    transport.connect()

    mock_serial_cls.assert_called_once_with("/dev/ttyUSB0", baudrate=115200, timeout=5)
    assert transport._serial is fake


def test_close_closes_and_is_idempotent():
    fake = FakeSerial()
    transport = make_device_transport(serial_double=fake)
    transport._in_raw_repl = True

    transport.close()
    assert fake.closed is True
    assert transport._serial is None
    assert transport._in_raw_repl is False

    # Second close is a no-op, not an error.
    transport.close()


def test_context_manager_connects_and_closes(mocker):
    fake = FakeSerial()
    mocker.patch.object(device_transport.serial, "Serial", return_value=fake)
    transport = make_device_transport(port="/dev/ttyUSB0")

    with transport as t:
        assert t is transport
        assert t._serial is fake

    assert fake.closed is True


def test_context_manager_closes_on_exception(mocker):
    fake = FakeSerial()
    mocker.patch.object(device_transport.serial, "Serial", return_value=fake)

    with pytest.raises(ValueError):
        with make_device_transport(port="/dev/ttyUSB0"):
            raise ValueError("boom")

    assert fake.closed is True


# --------------------------------------------------------------------------
# interrupt / raw REPL enter+exit
# --------------------------------------------------------------------------


def test_interrupt_writes_ctrl_c_and_flushes_pending_input():
    fake = FakeSerial(script=b"leftover boot banner\r\n")
    transport = make_device_transport(serial_double=fake)

    transport.interrupt()

    assert b"\r\x03" in fake.written
    assert fake.in_waiting == 0


def test_enter_raw_repl_with_soft_reset_success():
    script = (
        device_transport.RAW_REPL_PROMPT
        + device_transport.SOFT_REBOOT_MARKER
        + device_transport.RAW_REPL_BANNER
    )
    fake = FakeSerial(script=script)
    transport = make_device_transport(serial_double=fake)

    transport.enter_raw_repl(soft_reset=True)

    assert b"\r\x01" in fake.written
    assert device_transport.EOF_MARKER in fake.written
    assert transport._in_raw_repl is True


def test_enter_raw_repl_without_soft_reset_success():
    fake = FakeSerial(script=device_transport.RAW_REPL_BANNER)
    transport = make_device_transport(serial_double=fake)

    transport.enter_raw_repl(soft_reset=False)

    assert transport._in_raw_repl is True
    # No soft-reset ctrl-D should be sent when soft_reset=False.
    assert device_transport.EOF_MARKER not in fake.written


def test_enter_raw_repl_prompt_timeout_raises(mocker):
    fake = FakeSerial(script=b"not a prompt")
    transport = make_device_transport(serial_double=fake)
    mocker.patch.object(device_transport.time, "sleep")
    mocker.patch.object(
        device_transport.time, "monotonic", side_effect=itertools.count(0, 1000)
    )

    with pytest.raises(RawReplEntryError):
        transport.enter_raw_repl(soft_reset=True)


def test_enter_raw_repl_soft_reboot_timeout_raises(mocker):
    script = device_transport.RAW_REPL_PROMPT + b"garbage instead of soft reboot"
    fake = FakeSerial(script=script)
    transport = make_device_transport(serial_double=fake)
    mocker.patch.object(device_transport.time, "sleep")
    mocker.patch.object(
        device_transport.time, "monotonic", side_effect=itertools.count(0, 1000)
    )

    with pytest.raises(RawReplEntryError):
        transport.enter_raw_repl(soft_reset=True)


def test_enter_raw_repl_banner_timeout_raises(mocker):
    script = (
        device_transport.RAW_REPL_PROMPT
        + device_transport.SOFT_REBOOT_MARKER
        + b"not the banner"
    )
    fake = FakeSerial(script=script)
    transport = make_device_transport(serial_double=fake)
    mocker.patch.object(device_transport.time, "sleep")
    mocker.patch.object(
        device_transport.time, "monotonic", side_effect=itertools.count(0, 1000)
    )

    with pytest.raises(RawReplEntryError):
        transport.enter_raw_repl(soft_reset=True)


def test_exit_raw_repl_writes_ctrl_b():
    fake = FakeSerial()
    transport = make_device_transport(serial_double=fake)
    transport._in_raw_repl = True

    transport.exit_raw_repl()

    assert b"\r\x02" in fake.written
    assert transport._in_raw_repl is False


# --------------------------------------------------------------------------
# exec
# --------------------------------------------------------------------------


def test_exec_success_returns_stdout():
    script = (
        b">"
        + b"OK"
        + b"hello world"
        + device_transport.EOF_MARKER
        + device_transport.EOF_MARKER
    )
    fake = FakeSerial(script=script)
    transport = make_device_transport(serial_double=fake)

    result = transport.exec("print('hello world')")

    assert result == "hello world"


def test_exec_remote_traceback_raises_device_exec_error():
    script = (
        b">"
        + b"OK"
        + b"partial output"
        + device_transport.EOF_MARKER
        + b"Traceback: NameError"
        + device_transport.EOF_MARKER
    )
    fake = FakeSerial(script=script)
    transport = make_device_transport(serial_double=fake)

    with pytest.raises(DeviceExecError) as excinfo:
        transport.exec("undefined_name")

    assert excinfo.value.stdout == "partial output"
    assert excinfo.value.stderr == "Traceback: NameError"


def test_exec_bad_ack_raises_device_exec_error():
    fake = FakeSerial(script=b">" + b"XX")
    transport = make_device_transport(serial_double=fake)

    with pytest.raises(DeviceExecError):
        transport.exec("1 + 1")


def test_exec_no_prompt_raises_raw_repl_entry_error(mocker):
    fake = FakeSerial(script=b"no prompt here")
    transport = make_device_transport(serial_double=fake)
    mocker.patch.object(device_transport.time, "sleep")
    mocker.patch.object(
        device_transport.time, "monotonic", side_effect=itertools.count(0, 1000)
    )

    with pytest.raises(RawReplEntryError):
        transport.exec("1 + 1")


def test_exec_stdout_timeout_raises_device_exec_error(mocker):
    fake = FakeSerial(script=b">" + b"OK" + b"no eof marker")
    transport = make_device_transport(serial_double=fake)
    mocker.patch.object(device_transport.time, "sleep")
    mocker.patch.object(
        device_transport.time, "monotonic", side_effect=itertools.count(0, 1000)
    )

    with pytest.raises(DeviceExecError):
        transport.exec("1 + 1")


def test_exec_stderr_timeout_raises_device_exec_error(mocker):
    script = b">" + b"OK" + b"ok output" + device_transport.EOF_MARKER + b"no eof"
    fake = FakeSerial(script=script)
    transport = make_device_transport(serial_double=fake)
    mocker.patch.object(device_transport.time, "sleep")
    mocker.patch.object(
        device_transport.time, "monotonic", side_effect=itertools.count(0, 1000)
    )

    with pytest.raises(DeviceExecError):
        transport.exec("1 + 1")


# --------------------------------------------------------------------------
# ls
# --------------------------------------------------------------------------


def test_ls_parses_entries(mocker):
    transport = make_device_transport(serial_double=FakeSerial())
    mocker.patch.object(
        transport,
        "exec",
        return_value="10 False boot.py\n0 True lib\n",
    )

    entries = transport.ls(":")

    assert entries == [("boot.py", 10, False), ("lib", 0, True)]


def test_ls_strips_leading_colon_and_defaults_to_root(mocker):
    transport = make_device_transport(serial_double=FakeSerial())
    exec_mock = mocker.patch.object(transport, "exec", return_value="")

    transport.ls(":")

    sent_script = exec_mock.call_args[0][0]
    assert "'/'" in sent_script


def test_ls_empty_directory_returns_empty_list(mocker):
    transport = make_device_transport(serial_double=FakeSerial())
    mocker.patch.object(transport, "exec", return_value="")

    assert transport.ls(":lib") == []


def test_ls_skips_blank_lines(mocker):
    transport = make_device_transport(serial_double=FakeSerial())
    mocker.patch.object(
        transport, "exec", return_value="10 False boot.py\n\n0 True lib\n"
    )

    entries = transport.ls(":")

    assert entries == [("boot.py", 10, False), ("lib", 0, True)]


# --------------------------------------------------------------------------
# _read_until sleep-and-retry branch
# --------------------------------------------------------------------------


def test_read_until_sleeps_while_waiting_for_data(mocker):
    fake = FakeSerial(script=b"")
    transport = make_device_transport(serial_double=fake)
    sleep_mock = mocker.patch.object(device_transport.time, "sleep")
    mocker.patch.object(
        device_transport.time,
        "monotonic",
        side_effect=[0, 1, 2, 3, 100],
    )

    result = transport._read_until(b">")

    assert result == b""
    assert sleep_mock.call_count == 3


# --------------------------------------------------------------------------
# mkdir
# --------------------------------------------------------------------------


def test_mkdir_execs_idempotent_mkdir_script(mocker):
    transport = make_device_transport(serial_double=FakeSerial())
    exec_mock = mocker.patch.object(transport, "exec", return_value="")

    transport.mkdir(":lib")

    script = exec_mock.call_args[0][0]
    assert "os.mkdir('lib')" in script
    assert "e.args[0] != 17" in script


def test_mkdir_strips_leading_colon(mocker):
    transport = make_device_transport(serial_double=FakeSerial())
    exec_mock = mocker.patch.object(transport, "exec", return_value="")

    transport.mkdir("/already/absolute")

    assert "os.mkdir('/already/absolute')" in exec_mock.call_args[0][0]


# --------------------------------------------------------------------------
# put_file
# --------------------------------------------------------------------------


def test_put_file_writes_open_chunks_and_close(mocker, tmp_path):
    local_file = tmp_path / "boot.py"
    local_file.write_bytes(b"abcdefghij")  # 10 bytes, chunk_size=4 -> 3 chunks
    transport = make_device_transport(serial_double=FakeSerial())
    exec_mock = mocker.patch.object(transport, "exec", return_value="")

    transport.put_file(local_file, ":boot.py", chunk_size=4)

    calls = [call.args[0] for call in exec_mock.call_args_list]
    assert calls[0] == "f = open('boot.py', 'wb')\nw = f.write"
    assert calls[1] == "w(" + repr(b"abcd") + ")"
    assert calls[2] == "w(" + repr(b"efgh") + ")"
    assert calls[3] == "w(" + repr(b"ij") + ")"
    assert calls[4] == "f.close()"


def test_put_file_calls_on_start_before_writing(mocker, tmp_path):
    local_file = tmp_path / "boot.py"
    local_file.write_bytes(b"data")
    transport = make_device_transport(serial_double=FakeSerial())
    exec_mock = mocker.patch.object(transport, "exec", return_value="")
    seen = []

    transport.put_file(
        local_file,
        ":boot.py",
        on_start=lambda local, remote: seen.append((local, remote)),
    )

    assert seen == [(local_file, "boot.py")]
    assert (
        exec_mock.call_args_list[0].args[0] == "f = open('boot.py', 'wb')\nw = f.write"
    )


def test_put_file_empty_file_writes_no_chunks(mocker, tmp_path):
    local_file = tmp_path / "empty.py"
    local_file.write_bytes(b"")
    transport = make_device_transport(serial_double=FakeSerial())
    exec_mock = mocker.patch.object(transport, "exec", return_value="")

    transport.put_file(local_file, ":empty.py")

    calls = [call.args[0] for call in exec_mock.call_args_list]
    assert calls == ["f = open('empty.py', 'wb')\nw = f.write", "f.close()"]


# --------------------------------------------------------------------------
# put_dir
# --------------------------------------------------------------------------


def test_put_dir_uploads_nested_tree_without_wrapping_folder(mocker, tmp_path):
    (tmp_path / "boot.py").write_bytes(b"boot")
    lib_dir = tmp_path / "lib"
    lib_dir.mkdir()
    (lib_dir / "foo.py").write_bytes(b"foo")

    transport = make_device_transport(serial_double=FakeSerial())
    mkdir_mock = mocker.patch.object(transport, "mkdir")
    put_file_mock = mocker.patch.object(transport, "put_file")

    transport.put_dir(tmp_path, ":")

    mkdir_mock.assert_called_once_with("/lib")
    put_file_calls = {
        (str(call.args[0]), call.args[1]) for call in put_file_mock.call_args_list
    }
    assert put_file_calls == {
        (str(tmp_path / "boot.py"), "/boot.py"),
        (str(lib_dir / "foo.py"), "/lib/foo.py"),
    }


def test_put_dir_flat_directory_creates_no_subdirs(mocker, tmp_path):
    (tmp_path / "a.py").write_bytes(b"a")
    (tmp_path / "b.py").write_bytes(b"b")

    transport = make_device_transport(serial_double=FakeSerial())
    mkdir_mock = mocker.patch.object(transport, "mkdir")
    put_file_mock = mocker.patch.object(transport, "put_file")

    transport.put_dir(tmp_path, ":")

    mkdir_mock.assert_not_called()
    assert put_file_mock.call_count == 2


def test_put_dir_calls_on_file_with_index_and_total(mocker, tmp_path):
    (tmp_path / "a.py").write_bytes(b"a")
    (tmp_path / "b.py").write_bytes(b"b")

    transport = make_device_transport(serial_double=FakeSerial())
    mocker.patch.object(transport, "put_file")
    seen = []

    transport.put_dir(
        tmp_path,
        ":",
        on_file=lambda local, remote, index, total: seen.append(
            (local.name, remote, index, total)
        ),
    )

    assert seen == [
        ("a.py", "/a.py", 1, 2),
        ("b.py", "/b.py", 2, 2),
    ]
