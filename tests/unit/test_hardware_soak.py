import hashlib
import json
import subprocess
from pathlib import Path

import pytest
import serial

from device_transport import RawReplEntryError
from scripts import hardware_soak

OTA_CLEAN = (
    "SOAK_OTA_STATE_LEFT False\n"
    "SOAK_OTA_BACKUP_LEFT False\n"
    "SOAK_OTA_STAGED_LEFT False\n"
)


class FakeTransport:
    def __init__(self, outputs=None, fail_enter=False, file_contents=None):
        self.outputs = list(outputs or [])
        self.fail_enter = fail_enter
        self.calls = []
        self.closed = False
        self.file_contents = file_contents or {
            "ota-target-before.bin": b"before",
            "ota-target-after.bin": b"after",
            "ota-target-restored.bin": b"before",
        }

    def connect(self):
        self.calls.append("connect")

    def interrupt(self):
        self.calls.append("interrupt")

    def enter_raw_repl(self, soft_reset=True):
        self.calls.append(("enter_raw_repl", soft_reset))
        if self.fail_enter:
            raise RawReplEntryError("race")

    def exit_raw_repl(self):
        self.calls.append("exit_raw_repl")

    def close(self):
        self.closed = True

    def exec(self, code, timeout=None):
        self.calls.append(("exec", code, timeout))
        if self.outputs:
            return self.outputs.pop(0)
        return ""

    def get_file(self, remote, local):
        self.calls.append(("get_file", remote, Path(local).name))
        Path(local).write_bytes(self.file_contents[Path(local).name])

    def put_file(self, local, remote):
        self.calls.append(("put_file", Path(local).name, remote))


class FakeSerialStream:
    def __init__(self, output):
        self.output = bytearray(output)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    @property
    def in_waiting(self):
        return len(self.output)

    def read(self, size):
        if not self.output:
            return b""
        data = bytes(self.output[:size])
        del self.output[:size]
        return data


class FakeHttpResponse:
    def __init__(self, body):
        self.body = body.encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def read(self):
        return self.body


class FakeUrlOpener:
    def __init__(self, responses=None, error=None):
        self.responses = list(responses or [])
        self.error = error
        self.calls = []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        if self.error:
            raise self.error
        return FakeHttpResponse(self.responses.pop(0))


def make_soak(tmp_path, **kwargs):
    stages = kwargs.pop("stages", set())
    return hardware_soak.HardwareSoak(
        port=str(tmp_path / "ttyUSB0"),
        artifacts=tmp_path / "artifacts",
        stages=stages,
        **kwargs,
    )


def completed(stdout="", returncode=0):
    return subprocess.CompletedProcess([], returncode, stdout=stdout)


def test_fixture_http_handler_serves_only_registered_routes(mocker):
    mocker.patch.object(
        hardware_soak.BaseHTTPRequestHandler, "__init__", return_value=None
    )
    handler = hardware_soak.FixtureHttpHandler(
        routes={"/manifest.json": ("application/json", b"{}")}
    )
    handler.send_response = mocker.Mock()
    handler.send_header = mocker.Mock()
    handler.end_headers = mocker.Mock()
    handler.send_error = mocker.Mock()
    handler.wfile = mocker.Mock()

    handler.path = "/manifest.json"
    handler.do_GET()

    handler.send_response.assert_called_once_with(200)
    handler.wfile.write.assert_called_once_with(b"{}")

    handler.path = "/missing"
    handler.do_GET()

    handler.send_error.assert_called_once_with(404)
    handler.log_message("ignored")


@pytest.mark.parametrize("host", ["not-an-ip", "127.0.0.1", "0.0.0.0", "224.0.0.1"])
def test_validate_host_ip_rejects_unreachable_addresses(host):
    with pytest.raises(hardware_soak.SoakFailure, match="IPv4|device-reachable"):
        hardware_soak.validate_host_ip(host)


def test_validate_host_ip_accepts_lan_address():
    assert hardware_soak.validate_host_ip("192.168.1.50") == "192.168.1.50"


def test_discover_host_ip_uses_default_route(mocker):
    probe = mocker.MagicMock()
    probe.__enter__.return_value = probe
    probe.getsockname.return_value = ("192.168.1.50", 12345)
    socket_factory = mocker.patch.object(
        hardware_soak.socket, "socket", return_value=probe
    )

    assert hardware_soak.discover_host_ip() == "192.168.1.50"
    socket_factory.assert_called_once_with(
        hardware_soak.socket.AF_INET, hardware_soak.socket.SOCK_DGRAM
    )
    probe.connect.assert_called_once_with(hardware_soak.LOCAL_OTA_ROUTE)


def test_discover_host_ip_reports_missing_route(mocker):
    probe = mocker.MagicMock()
    probe.__enter__.return_value = probe
    probe.connect.side_effect = OSError("offline")
    mocker.patch.object(hardware_soak.socket, "socket", return_value=probe)

    with pytest.raises(hardware_soak.SoakFailure, match="--ota-host-ip"):
        hardware_soak.discover_host_ip()


def test_local_http_server_stops_after_failure(mocker):
    server = mocker.MagicMock()
    server.server_address = ("192.168.1.50", 4321)
    server_cls = mocker.patch.object(
        hardware_soak, "ThreadingHTTPServer", return_value=server
    )
    thread = mocker.MagicMock()
    mocker.patch.object(hardware_soak.threading, "Thread", return_value=thread)

    with pytest.raises(RuntimeError, match="stop"):
        with hardware_soak.local_http_server("192.168.1.50", 0) as result:
            assert result == (4321, {})
            raise RuntimeError("stop")

    server_cls.assert_called_once()
    thread.start.assert_called_once_with()
    server.shutdown.assert_called_once_with()
    server.server_close.assert_called_once_with()
    thread.join.assert_called_once_with(timeout=5)


def test_local_http_server_reports_bind_failure(mocker):
    mocker.patch.object(
        hardware_soak, "ThreadingHTTPServer", side_effect=OSError("in use")
    )

    with pytest.raises(hardware_soak.SoakFailure, match="could not start"):
        with hardware_soak.local_http_server("192.168.1.50", 8000):
            pass


def test_git_commit_is_unknown_when_git_is_unavailable(mocker, tmp_path):
    mocker.patch.object(hardware_soak.shutil, "which", return_value=None)

    soak = make_soak(tmp_path)

    assert soak.report["commit"] == "unknown"


def test_raw_repl_session_uses_non_resetting_entry_and_closes(mocker):
    transport = FakeTransport()
    mocker.patch.object(hardware_soak, "DeviceTransport", return_value=transport)

    with hardware_soak.raw_repl_session("/dev/ttyUSB0") as yielded:
        assert yielded is transport

    assert ("enter_raw_repl", False) in transport.calls
    assert "exit_raw_repl" in transport.calls
    assert transport.closed is True


def test_raw_repl_session_retries_handshake_race(mocker):
    failed = FakeTransport(fail_enter=True)
    working = FakeTransport()
    constructor = mocker.patch.object(
        hardware_soak, "DeviceTransport", side_effect=[failed, working]
    )
    mocker.patch.object(hardware_soak.time, "sleep")

    with hardware_soak.raw_repl_session("/dev/ttyUSB0"):
        pass

    assert constructor.call_count == 2
    assert failed.closed is True


def test_raw_repl_session_reports_exhausted_retries(mocker):
    mocker.patch.object(
        hardware_soak,
        "DeviceTransport",
        side_effect=[FakeTransport(fail_enter=True) for _ in range(4)],
    )
    mocker.patch.object(hardware_soak.time, "sleep")

    with pytest.raises(RawReplEntryError, match="after 4 attempts"):
        with hardware_soak.raw_repl_session("/dev/ttyUSB0"):
            pass


def test_raw_repl_session_ignores_exit_error_but_still_closes(mocker):
    transport = FakeTransport()
    transport.exit_raw_repl = mocker.Mock(side_effect=RuntimeError("lost"))
    mocker.patch.object(hardware_soak, "DeviceTransport", return_value=transport)

    with hardware_soak.raw_repl_session("/dev/ttyUSB0"):
        pass

    assert transport.closed is True


def test_raw_repl_session_retries_serial_open_error(mocker):
    failed = FakeTransport()
    failed.connect = mocker.Mock(side_effect=serial.SerialException("busy"))
    working = FakeTransport()
    mocker.patch.object(hardware_soak, "DeviceTransport", side_effect=[failed, working])
    mocker.patch.object(hardware_soak.time, "sleep")

    with hardware_soak.raw_repl_session("/dev/ttyUSB0"):
        pass

    assert failed.closed is True


def test_tinker_records_output_and_raises_on_failure(tmp_path):
    results = [completed("device details\n"), completed("bad\n", returncode=1)]
    soak = make_soak(tmp_path, command_runner=lambda *args, **kwargs: results.pop(0))
    soak.artifacts.mkdir()

    output = soak._tinker("device", "info", log_name="info.log")

    assert output == "device details\n"
    assert (soak.artifacts / "info.log").read_text() == output
    with pytest.raises(hardware_soak.SoakFailure, match="device reset failed"):
        soak._tinker("device", "reset")


def test_prepare_backs_up_device_and_records_baseline(tmp_path, mocker):
    port = tmp_path / "ttyUSB0"
    port.touch()

    def runner(command, **_kwargs):
        if "backup" in command:
            soak.backup_staging.mkdir()
        return completed("ok\n")

    soak = make_soak(tmp_path, command_runner=runner)
    mocker.patch.object(soak, "_git_commit", return_value="abc")

    soak.prepare()

    assert soak.backup.parent == soak.artifacts
    assert soak.report["stages"]["prepare"]["result"] == "passed"
    assert (soak.artifacts / "device-info.log").exists()


def test_backup_device_hard_resets_and_retries_atomically(tmp_path):
    commands = []
    backup_attempts = 0

    def runner(command, **_kwargs):
        nonlocal backup_attempts
        commands.append(command)
        if "backup" in command:
            backup_attempts += 1
            soak.backup_staging.mkdir()
            if backup_attempts == 1:
                return completed("race\n", returncode=1)
        return completed("ok\n")

    soak = make_soak(tmp_path, command_runner=runner)
    soak.artifacts.mkdir()
    soak.backup_staging.mkdir()

    soak._backup_device()

    assert backup_attempts == 2
    assert soak.backup.is_dir()
    assert not soak.backup_staging.exists()
    assert any(command[2:4] == ["device", "reset"] for command in commands)
    assert any(command[2:4] == ["device", "info"] for command in commands)


def test_backup_device_removes_partial_backup_after_second_failure(tmp_path):
    def runner(command, **_kwargs):
        if "backup" in command:
            soak.backup_staging.mkdir()
            return completed("race\n", returncode=1)
        return completed("ok\n")

    soak = make_soak(tmp_path, command_runner=runner)
    soak.artifacts.mkdir()

    with pytest.raises(hardware_soak.SoakFailure, match="backup"):
        soak._backup_device()

    assert not soak.backup.exists()
    assert not soak.backup_staging.exists()


def test_prepare_rejects_missing_port(tmp_path):
    soak = make_soak(tmp_path)

    with pytest.raises(hardware_soak.SoakFailure, match="does not exist"):
        soak.prepare()


def test_prepare_does_not_reuse_artifact_directory(tmp_path):
    port = tmp_path / "ttyUSB0"
    port.touch()
    soak = make_soak(tmp_path)
    soak.artifacts.mkdir()

    with pytest.raises(FileExistsError):
        soak.prepare()


def test_restore_attempts_backup_even_when_transient_cleanup_fails(tmp_path, mocker):
    soak = make_soak(tmp_path)
    tinker = mocker.patch.object(soak, "_tinker")
    mocker.patch.object(
        soak, "_cleanup_transients", side_effect=RuntimeError("raw repl failed")
    )

    with pytest.raises(hardware_soak.SoakFailure, match="could not be removed"):
        soak.restore()

    assert [call.args[:2] for call in tinker.call_args_list] == [
        ("device", "reset"),
        ("restore", "--port"),
        ("device", "reset"),
    ]


def test_restore_marks_success_after_cleanup_and_restore(tmp_path, mocker):
    soak = make_soak(tmp_path)
    mocker.patch.object(soak, "_tinker")
    mocker.patch.object(soak, "_cleanup_transients")

    soak.restore()

    assert soak.restored is True


def test_provisioning_requires_explicit_destructive_confirmation(tmp_path):
    soak = make_soak(tmp_path, input_fn=lambda _prompt: "no")

    with pytest.raises(hardware_soak.SoakFailure, match="not confirmed"):
        soak.provisioning()


def test_provisioning_verifies_persisted_wifi_and_restores(tmp_path, mocker):
    answers = iter(["PROVISION", ""])
    soak = make_soak(tmp_path, input_fn=lambda _prompt: next(answers))
    mocker.patch.object(soak, "_tinker")
    submit = mocker.patch.object(soak, "_submit_provisioning_form")
    restore = mocker.patch.object(soak, "restore")
    transport = FakeTransport(outputs=["SOAK_CONFIG_FILE True\nSOAK_WIFI_SET True\n"])
    mocker.patch.object(
        hardware_soak, "raw_repl_session", return_value=mocker.MagicMock()
    )
    hardware_soak.raw_repl_session.return_value.__enter__.return_value = transport

    soak.provisioning()

    assert soak.report["stages"]["provisioning"]["result"] == "passed"
    assert soak.report["stages"]["provisioning"]["submission_mode"] == "automatic"
    submit.assert_called_once_with()
    restore.assert_called_once_with()


def test_provisioning_accepts_browser_completed_submission(tmp_path, mocker):
    answers = iter(["PROVISION", "done"])
    soak = make_soak(tmp_path, input_fn=lambda _prompt: next(answers))
    mocker.patch.object(soak, "_tinker")
    submit = mocker.patch.object(soak, "_submit_provisioning_form")
    mocker.patch.object(soak, "restore")
    transport = FakeTransport(outputs=["SOAK_CONFIG_FILE True\nSOAK_WIFI_SET True\n"])
    context = mocker.MagicMock()
    context.__enter__.return_value = transport
    mocker.patch.object(hardware_soak, "raw_repl_session", return_value=context)

    soak.provisioning()

    submit.assert_not_called()
    assert soak.report["stages"]["provisioning"]["submission_mode"] == "manual"


def test_provisioning_rejects_empty_wifi(tmp_path, mocker):
    answers = iter(["PROVISION", "anything is accepted here"])
    soak = make_soak(tmp_path, input_fn=lambda _prompt: next(answers))
    mocker.patch.object(soak, "_tinker")
    mocker.patch.object(soak, "_submit_provisioning_form")
    context = mocker.MagicMock()
    context.__enter__.return_value = FakeTransport(
        outputs=["SOAK_CONFIG_FILE True\nSOAK_WIFI_SET False\n"]
    )
    mocker.patch.object(hardware_soak, "raw_repl_session", return_value=context)
    with pytest.raises(hardware_soak.SoakFailure, match="empty WiFi SSID"):
        soak.provisioning()


def test_provisioning_reports_config_file_verification_error(tmp_path, mocker):
    answers = iter(["PROVISION", ""])
    soak = make_soak(tmp_path, input_fn=lambda _prompt: next(answers))
    mocker.patch.object(soak, "_tinker")
    mocker.patch.object(soak, "_submit_provisioning_form")
    context = mocker.MagicMock()
    context.__enter__.return_value = FakeTransport(
        outputs=["SOAK_CONFIG_FILE False\nSOAK_CONFIG_ERROR OSError\n"]
    )
    mocker.patch.object(hardware_soak, "raw_repl_session", return_value=context)

    with pytest.raises(hardware_soak.SoakFailure, match="OSError"):
        soak.provisioning()


def test_provisioning_reports_empty_verification_output(tmp_path, mocker):
    answers = iter(["PROVISION", ""])
    soak = make_soak(tmp_path, input_fn=lambda _prompt: next(answers))
    mocker.patch.object(soak, "_tinker")
    mocker.patch.object(soak, "_submit_provisioning_form")
    context = mocker.MagicMock()
    context.__enter__.return_value = FakeTransport(outputs=[""])
    mocker.patch.object(hardware_soak, "raw_repl_session", return_value=context)

    with pytest.raises(hardware_soak.SoakFailure, match="no output"):
        soak.provisioning()


def test_submit_provisioning_form_uses_private_backup_without_logging_secrets(
    tmp_path,
):
    opener = FakeUrlOpener(
        responses=[
            '<h1>Microweaver WiFi Setup</h1><form action="/save">',
            "Credentials saved. Connected!",
        ]
    )
    soak = make_soak(tmp_path, url_opener=opener)
    soak.backup.mkdir(parents=True)
    (soak.backup / "device_config.json").write_text(
        '{"wifi_ssid": "TestWifi", "wifi_password": "super-secret"}'
    )

    soak._submit_provisioning_form()

    form_request, form_timeout = opener.calls[0]
    save_request, save_timeout = opener.calls[1]
    assert form_request.full_url == "http://192.168.4.1/"
    assert form_timeout == 10
    assert save_request.full_url == "http://192.168.4.1/save"
    assert save_request.get_method() == "POST"
    assert save_timeout == 35
    assert b"ssid=TestWifi" in save_request.data
    assert b"password=super-secret" in save_request.data


@pytest.mark.parametrize(
    ("config", "message"),
    [
        (None, "FileNotFoundError"),
        ("not-json", "JSONDecodeError"),
        ('{"wifi_ssid": ""}', "has no WiFi SSID"),
    ],
)
def test_submit_provisioning_form_rejects_unusable_private_backup(
    tmp_path, config, message
):
    soak = make_soak(tmp_path, url_opener=FakeUrlOpener())
    soak.backup.mkdir(parents=True)
    if config is not None:
        (soak.backup / "device_config.json").write_text(config)

    with pytest.raises(hardware_soak.SoakFailure, match=message):
        soak._submit_provisioning_form()


def test_submit_provisioning_form_rejects_wrong_page(tmp_path):
    opener = FakeUrlOpener(responses=["not the setup form"])
    soak = make_soak(tmp_path, url_opener=opener)
    soak.backup.mkdir(parents=True)
    (soak.backup / "device_config.json").write_text(
        '{"wifi_ssid": "TestWifi", "wifi_password": "changeme"}'
    )

    with pytest.raises(hardware_soak.SoakFailure, match="did not return"):
        soak._submit_provisioning_form()


def test_submit_provisioning_form_rejects_failed_wifi_test(tmp_path):
    opener = FakeUrlOpener(
        responses=[
            '<h1>Microweaver WiFi Setup</h1><form action="/save">',
            "Credentials saved, but could not connect.",
        ]
    )
    soak = make_soak(tmp_path, url_opener=opener)
    soak.backup.mkdir(parents=True)
    (soak.backup / "device_config.json").write_text(
        '{"wifi_ssid": "TestWifi", "wifi_password": "changeme"}'
    )

    with pytest.raises(hardware_soak.SoakFailure, match="could not connect"):
        soak._submit_provisioning_form()


def test_submit_provisioning_form_sanitizes_http_exception(tmp_path):
    opener = FakeUrlOpener(error=OSError("sensitive detail"))
    soak = make_soak(tmp_path, url_opener=opener)
    soak.backup.mkdir(parents=True)
    (soak.backup / "device_config.json").write_text(
        '{"wifi_ssid": "TestWifi", "wifi_password": "changeme"}'
    )

    with pytest.raises(hardware_soak.SoakFailure, match="OSError") as failure:
        soak._submit_provisioning_form()
    assert "sensitive detail" not in str(failure.value)


def test_ota_requires_manifest_and_existing_target(tmp_path):
    soak = make_soak(tmp_path)

    with pytest.raises(hardware_soak.SoakFailure, match="requires"):
        soak.ota()

    soak.manifest_url = "https://firmware.example.test/manifest.json"
    soak.ota_target = "/device_config.json"
    with pytest.raises(hardware_soak.SoakFailure, match="cannot be used"):
        soak.ota()


def test_ota_local_fixture_rejects_conflicting_or_unsafe_target(tmp_path):
    soak = make_soak(
        tmp_path,
        local_ota_fixture=True,
        manifest_url="https://firmware.example.test/manifest.json",
    )
    with pytest.raises(hardware_soak.SoakFailure, match="cannot be combined"):
        soak.ota()

    soak.manifest_url = None
    soak.ota_target = "main.py"
    with pytest.raises(hardware_soak.SoakFailure, match="only supports boot.py"):
        soak.ota()

    soak.local_ota_fixture = False
    soak.ota_target = "boot.py"
    soak.manifest_url = "https://firmware.example.test/manifest.json"
    soak.ota_port = 8000
    with pytest.raises(hardware_soak.SoakFailure, match="require"):
        soak.ota()


def test_local_ota_manifest_serves_changed_boot_fixture(tmp_path, mocker):
    before = tmp_path / "boot-before.py"
    before.write_bytes(b"print('boot')\n")
    soak = make_soak(
        tmp_path,
        local_ota_fixture=True,
        ota_target="boot.py",
        ota_host_ip="192.168.1.50",
    )
    routes = {}
    server = mocker.MagicMock()
    server.__enter__.return_value = (8765, routes)
    mocker.patch.object(hardware_soak, "local_http_server", return_value=server)

    with soak._ota_manifest(before) as (manifest_url, expected_sha256):
        manifest = json.loads(routes["/manifest.json"][1])
        payload = routes["/boot.py"][1]

        assert manifest_url == "http://192.168.1.50:8765/manifest.json"
        assert payload.startswith(before.read_bytes())
        assert b"Microweaver OTA fixture" in payload
        assert expected_sha256 == hashlib.sha256(payload).hexdigest()
        assert manifest["files"]["boot.py"]["sha256"] == expected_sha256
        assert manifest["files"]["boot.py"]["url"].endswith("/boot.py")
        assert manifest["version"].startswith("soak-")


def test_local_ota_manifest_auto_discovers_host(tmp_path, mocker):
    before = tmp_path / "boot-before.py"
    before.write_text("print('boot')\n")
    soak = make_soak(tmp_path, local_ota_fixture=True, ota_target="boot.py")
    discover = mocker.patch.object(
        hardware_soak, "discover_host_ip", return_value="192.168.1.51"
    )
    server = mocker.MagicMock()
    server.__enter__.return_value = (8765, {})
    mocker.patch.object(hardware_soak, "local_http_server", return_value=server)

    with soak._ota_manifest(before) as (manifest_url, _):
        assert manifest_url.startswith("http://192.168.1.51:8765/")

    discover.assert_called_once_with()


def test_local_ota_manifest_rejects_non_utf8_target(tmp_path):
    before = tmp_path / "boot-before.py"
    before.write_bytes(b"\xff")
    soak = make_soak(
        tmp_path,
        local_ota_fixture=True,
        ota_target="boot.py",
        ota_host_ip="192.168.1.50",
    )

    with pytest.raises(hardware_soak.SoakFailure, match="UTF-8"):
        with soak._ota_manifest(before):
            pass


def test_ota_local_fixture_applies_expected_bytes_and_rolls_back(tmp_path, mocker):
    expected_sha256 = hashlib.sha256(b"after").hexdigest()
    soak = make_soak(
        tmp_path,
        local_ota_fixture=True,
        ota_host_ip="192.168.1.50",
    )
    soak.artifacts.mkdir()
    transport = FakeTransport(
        outputs=[
            "SOAK_OTA_APPLIED True\n",
            "SOAK_OTA_STATE True\nSOAK_OTA_BACKUP True\n",
            "SOAK_OTA_ROLLED_BACK True\n",
            OTA_CLEAN,
        ]
    )
    context = mocker.MagicMock()
    context.__enter__.return_value = transport
    mocker.patch.object(hardware_soak, "raw_repl_session", return_value=context)
    fixture = mocker.patch.object(soak, "_ota_manifest")
    fixture.return_value.__enter__.return_value = (
        "http://192.168.1.50:8765/manifest.json",
        expected_sha256,
    )

    soak.ota()

    evidence = soak.report["stages"]["ota"]
    assert soak.ota_target == "boot.py"
    assert evidence["local_fixture"] is True
    assert evidence["expected_sha256"] == evidence["applied_sha256"]
    apply_code = next(
        call[1]
        for call in transport.calls
        if call[0] == "exec" and "SOAK_OTA_APPLIED" in call[1]
    )
    assert "WiFiService" in apply_code
    assert (soak.artifacts / "ota-apply.log").read_text() == "SOAK_OTA_APPLIED True\n"


@pytest.mark.parametrize(
    ("cleanup", "message"),
    [
        (OTA_CLEAN.replace("STATE_LEFT False", "STATE_LEFT True"), "OTA state"),
        (OTA_CLEAN.replace("BACKUP_LEFT False", "BACKUP_LEFT True"), "OTA backup"),
        (OTA_CLEAN.replace("STAGED_LEFT False", "STAGED_LEFT True"), "OTA staged file"),
    ],
)
def test_ota_rejects_rollback_residue(tmp_path, mocker, cleanup, message):
    soak = make_soak(
        tmp_path,
        manifest_url="https://firmware.example.test/manifest.json",
        ota_target="boot.py",
    )
    soak.artifacts.mkdir()
    transport = FakeTransport(
        outputs=[
            "SOAK_OTA_APPLIED True\n",
            "SOAK_OTA_STATE True\nSOAK_OTA_BACKUP True\n",
            "SOAK_OTA_ROLLED_BACK True\n",
            cleanup,
        ]
    )
    context = mocker.MagicMock()
    context.__enter__.return_value = transport
    mocker.patch.object(hardware_soak, "raw_repl_session", return_value=context)

    with pytest.raises(hardware_soak.SoakFailure, match=message):
        soak.ota()


def test_ota_local_fixture_rejects_applied_checksum_mismatch(tmp_path, mocker):
    soak = make_soak(
        tmp_path,
        local_ota_fixture=True,
        ota_target="boot.py",
        ota_host_ip="192.168.1.50",
    )
    soak.artifacts.mkdir()
    transport = FakeTransport(
        outputs=[
            "SOAK_OTA_APPLIED True\n",
            "SOAK_OTA_STATE True\nSOAK_OTA_BACKUP True\n",
            "SOAK_OTA_ROLLED_BACK True\n",
            OTA_CLEAN,
        ]
    )
    context = mocker.MagicMock()
    context.__enter__.return_value = transport
    mocker.patch.object(hardware_soak, "raw_repl_session", return_value=context)
    fixture = mocker.patch.object(soak, "_ota_manifest")
    fixture.return_value.__enter__.return_value = (
        "http://fixture/manifest.json",
        "bad",
    )

    with pytest.raises(hardware_soak.SoakFailure, match="fixture checksum"):
        soak.ota()


def test_ota_applies_real_download_and_byte_verifies_rollback(tmp_path, mocker):
    soak = make_soak(
        tmp_path,
        manifest_url="https://firmware.example.test/manifest.json",
        ota_target="main.mpy",
    )
    soak.artifacts.mkdir()
    transport = FakeTransport(
        outputs=[
            "SOAK_OTA_APPLIED True\n",
            "SOAK_OTA_STATE True\nSOAK_OTA_BACKUP True\n",
            "SOAK_OTA_ROLLED_BACK True\n",
            OTA_CLEAN,
        ]
    )
    context = mocker.MagicMock()
    context.__enter__.return_value = transport
    mocker.patch.object(hardware_soak, "raw_repl_session", return_value=context)

    soak.ota()

    evidence = soak.report["stages"]["ota"]
    assert evidence["result"] == "passed"
    assert evidence["before_sha256"] == evidence["restored_sha256"]
    assert evidence["before_sha256"] != evidence["applied_sha256"]


@pytest.mark.parametrize(
    ("outputs", "message"),
    [
        (["SOAK_OTA_APPLIED False\n"], "did not apply"),
        (
            ["SOAK_OTA_APPLIED True\n", "SOAK_OTA_STATE False\n"],
            "state was not persisted",
        ),
        (
            [
                "SOAK_OTA_APPLIED True\n",
                "SOAK_OTA_STATE True\nSOAK_OTA_BACKUP False\n",
            ],
            "was not backed up",
        ),
        (
            [
                "SOAK_OTA_APPLIED True\n",
                "SOAK_OTA_STATE True\nSOAK_OTA_BACKUP True\n",
                "SOAK_OTA_ROLLED_BACK False\n",
            ],
            "rollback did not run",
        ),
    ],
)
def test_ota_rejects_missing_hardware_evidence(tmp_path, mocker, outputs, message):
    soak = make_soak(
        tmp_path,
        manifest_url="https://firmware.example.test/manifest.json",
        ota_target="main.mpy",
    )
    soak.artifacts.mkdir()
    context = mocker.MagicMock()
    context.__enter__.return_value = FakeTransport(outputs=outputs)
    mocker.patch.object(hardware_soak, "raw_repl_session", return_value=context)

    with pytest.raises(hardware_soak.SoakFailure, match=message):
        soak.ota()


@pytest.mark.parametrize(
    ("file_contents", "message"),
    [
        (
            {
                "ota-target-before.bin": b"same",
                "ota-target-after.bin": b"same",
                "ota-target-restored.bin": b"same",
            },
            "did not change",
        ),
        (
            {
                "ota-target-before.bin": b"before",
                "ota-target-after.bin": b"after",
                "ota-target-restored.bin": b"wrong",
            },
            "did not restore",
        ),
    ],
)
def test_ota_rejects_byte_comparison_failure(tmp_path, mocker, file_contents, message):
    soak = make_soak(
        tmp_path,
        manifest_url="https://firmware.example.test/manifest.json",
        ota_target="main.mpy",
    )
    soak.artifacts.mkdir()
    transport = FakeTransport(
        outputs=[
            "SOAK_OTA_APPLIED True\n",
            "SOAK_OTA_STATE True\nSOAK_OTA_BACKUP True\n",
            "SOAK_OTA_ROLLED_BACK True\n",
            OTA_CLEAN,
        ],
        file_contents=file_contents,
    )
    context = mocker.MagicMock()
    context.__enter__.return_value = transport
    mocker.patch.object(hardware_soak, "raw_repl_session", return_value=context)

    with pytest.raises(hardware_soak.SoakFailure, match=message):
        soak.ota()


def test_recovery_captures_ordered_watchdog_boot_loop_and_safe_mode(tmp_path, mocker):
    output = (
        b'{"reason": "watchdog"}\n'
        b"BOOT: boot-loop detected, entering safe mode\n"
        b"SOAK: safe mode reached\n"
    )
    soak = make_soak(
        tmp_path,
        watch_seconds=1,
        serial_cls=lambda *a, **k: FakeSerialStream(output),
    )
    soak.artifacts.mkdir()
    transport = FakeTransport()
    context = mocker.MagicMock()
    context.__enter__.return_value = transport
    mocker.patch.object(hardware_soak, "raw_repl_session", return_value=context)
    mocker.patch.object(soak, "_tinker")
    mocker.patch.object(hardware_soak.time, "monotonic", side_effect=[0, 0, 0.5, 1.1])

    soak.recovery()

    assert soak.watchdog_probe_installed is True
    evidence = soak.report["stages"]["recovery"]
    assert evidence["watchdog_reset_observed"] is True
    assert evidence["boot_loop_detected"] is True
    assert evidence["safe_mode_observed"] is True
    assert evidence["evidence_ordered"] is True
    assert (soak.artifacts / "watchdog-recovery.log").read_bytes() == output


@pytest.mark.parametrize(
    ("output", "message"),
    [
        (
            b"BOOT: boot-loop detected, entering safe mode\n"
            b"SOAK: safe mode reached\n",
            "reset reason was not observed",
        ),
        (
            b'{"reason": "watchdog"}\nSOAK: safe mode reached\n',
            "boot-loop detection was not observed",
        ),
        (
            b'{"reason": "watchdog"}\n'
            b"BOOT: boot-loop detected, entering safe mode\n",
            "did not reach safe mode",
        ),
        (
            b"SOAK: safe mode reached\n"
            b"BOOT: boot-loop detected, entering safe mode\n"
            b'{"reason": "watchdog"}\n',
            "watchdog, boot-loop, safe-mode order",
        ),
    ],
)
def test_recovery_requires_ordered_watchdog_boot_loop_and_safe_mode_evidence(
    tmp_path, mocker, output, message
):
    soak = make_soak(
        tmp_path,
        watch_seconds=1,
        serial_cls=lambda *a, **k: FakeSerialStream(output),
    )
    soak.artifacts.mkdir()
    context = mocker.MagicMock()
    context.__enter__.return_value = FakeTransport()
    mocker.patch.object(hardware_soak, "raw_repl_session", return_value=context)
    mocker.patch.object(soak, "_tinker")
    mocker.patch.object(hardware_soak.time, "monotonic", side_effect=[0, 0, 0.5, 1.1])

    with pytest.raises(hardware_soak.SoakFailure, match=message):
        soak.recovery()


def test_cleanup_removes_only_transients_created_by_selected_phases(tmp_path, mocker):
    soak = make_soak(
        tmp_path,
        manifest_url="https://firmware.example.test/manifest.json",
        ota_target="main.mpy",
    )
    soak.ota_attempted = True
    soak.watchdog_probe_installed = True
    transport = FakeTransport()
    context = mocker.MagicMock()
    context.__enter__.return_value = transport
    mocker.patch.object(hardware_soak, "raw_repl_session", return_value=context)

    soak._cleanup_transients()

    code = "\n".join(call[1] for call in transport.calls if call[0] == "exec")
    assert "main.py" in code
    assert "main.mpy.ota_bak" in code
    assert "soak_ota_state.json" in code


def test_burn_in_captures_serial_and_counts_reset_events(tmp_path, mocker):
    output = b'{"event": "reset"}\nhealthy\n'
    soak = make_soak(
        tmp_path,
        burn_in_hours=0.001,
        serial_cls=lambda *a, **k: FakeSerialStream(output),
    )
    soak.artifacts.mkdir()
    mocker.patch.object(soak, "_tinker")
    mocker.patch.object(hardware_soak.time, "monotonic", side_effect=[0, 0, 1, 4])

    soak.burn_in()

    evidence = soak.report["stages"]["burnin"]
    assert evidence["reset_events_observed"] == 1
    assert evidence["bytes_captured"] == len(output)
    assert (soak.artifacts / "burn-in.log").read_bytes() == output


def test_burn_in_rejects_empty_serial_capture(tmp_path, mocker):
    soak = make_soak(
        tmp_path,
        burn_in_hours=0.001,
        serial_cls=lambda *a, **k: FakeSerialStream(b""),
    )
    soak.artifacts.mkdir()
    mocker.patch.object(soak, "_tinker")
    mocker.patch.object(hardware_soak.time, "monotonic", side_effect=[0, 0, 1, 4])

    with pytest.raises(hardware_soak.SoakFailure, match="no device serial"):
        soak.burn_in()


def test_run_restores_and_deletes_private_backup_on_success(tmp_path, mocker):
    soak = make_soak(tmp_path)

    def prepare():
        soak.artifacts.mkdir()
        soak.artifacts_created = True
        soak.backup.mkdir()

    mocker.patch.object(soak, "prepare", side_effect=prepare)

    def restore():
        soak.restored = True

    mocker.patch.object(soak, "restore", side_effect=restore)

    report = soak.run()

    assert report["result"] == "passed"
    assert report["restored"] is True
    assert not soak.backup.exists()


def test_run_dispatches_all_selected_phases(tmp_path, mocker):
    soak = make_soak(tmp_path, stages={"provisioning", "ota", "recovery", "burnin"})

    def prepare():
        soak.artifacts.mkdir()
        soak.artifacts_created = True
        soak.backup.mkdir()

    mocker.patch.object(soak, "prepare", side_effect=prepare)
    provisioning = mocker.patch.object(soak, "provisioning")
    ota = mocker.patch.object(soak, "ota")
    recovery = mocker.patch.object(soak, "recovery")
    burn_in = mocker.patch.object(soak, "burn_in")
    restore = mocker.patch.object(soak, "restore")

    soak.run()

    provisioning.assert_called_once_with()
    ota.assert_called_once_with()
    recovery.assert_called_once_with()
    burn_in.assert_called_once_with()
    assert restore.call_count == 2


def test_run_reports_failure_and_still_restores(tmp_path, mocker):
    soak = make_soak(tmp_path, stages={"ota"})

    def prepare():
        soak.artifacts.mkdir()
        soak.artifacts_created = True
        soak.backup.mkdir()

    mocker.patch.object(soak, "prepare", side_effect=prepare)
    mocker.patch.object(
        soak, "ota", side_effect=hardware_soak.SoakFailure("apply failed")
    )
    restore = mocker.patch.object(soak, "restore")

    with pytest.raises(hardware_soak.SoakFailure, match="apply failed"):
        soak.run()

    restore.assert_called_once_with()
    report = __import__("json").loads((soak.artifacts / "report.json").read_text())
    assert report["result"] == "failed"
    assert report["restored"] is True


def test_run_keeps_backup_when_restore_fails(tmp_path, mocker):
    soak = make_soak(tmp_path)

    def prepare():
        soak.artifacts.mkdir()
        soak.artifacts_created = True
        soak.backup.mkdir()

    mocker.patch.object(soak, "prepare", side_effect=prepare)
    mocker.patch.object(soak, "restore", side_effect=RuntimeError("port busy"))

    with pytest.raises(hardware_soak.SoakFailure, match="port busy"):
        soak.run()

    assert soak.backup.exists()
    assert soak.report["restored"] is False


def test_run_removes_incomplete_staged_backup(tmp_path, mocker):
    soak = make_soak(tmp_path)

    def prepare():
        soak.artifacts.mkdir()
        soak.artifacts_created = True
        soak.backup_staging.mkdir()
        raise hardware_soak.SoakFailure("backup failed")

    mocker.patch.object(soak, "prepare", side_effect=prepare)

    with pytest.raises(hardware_soak.SoakFailure, match="backup failed"):
        soak.run()

    assert not soak.backup_staging.exists()
    assert "restored" not in soak.report


def test_parse_args_validates_stages(tmp_path):
    args = hardware_soak.parse_args(
        ["--port", str(tmp_path / "tty"), "--stages", "ota,recovery"]
    )
    assert args.stages == {"ota", "recovery"}

    with pytest.raises(SystemExit):
        hardware_soak.parse_args(
            ["--port", str(tmp_path / "tty"), "--stages", "unknown"]
        )


def test_parse_args_accepts_local_ota_fixture(tmp_path):
    args = hardware_soak.parse_args(
        [
            "--port",
            str(tmp_path / "tty"),
            "--stages",
            "ota",
            "--ota-local-fixture",
            "--ota-host-ip",
            "192.168.1.50",
            "--ota-port",
            "8000",
        ]
    )

    assert args.ota_local_fixture is True
    assert args.ota_host_ip == "192.168.1.50"
    assert args.ota_port == 8000


@pytest.mark.parametrize(
    "extra",
    [
        [
            "--ota-local-fixture",
            "--ota-manifest-url",
            "https://firmware.example.test/manifest.json",
        ],
        ["--ota-local-fixture", "--ota-target", "main.py"],
        ["--ota-host-ip", "192.168.1.50"],
        ["--ota-port", "8000"],
        ["--ota-local-fixture", "--ota-port", "65536"],
    ],
)
def test_parse_args_rejects_invalid_local_ota_options(tmp_path, extra):
    with pytest.raises(SystemExit):
        hardware_soak.parse_args(
            ["--port", str(tmp_path / "tty"), "--stages", "ota", *extra]
        )


def test_main_returns_success_or_failure(tmp_path, mocker):
    passed = mocker.patch.object(hardware_soak.HardwareSoak, "run")
    passed.return_value = {"result": "passed"}
    assert (
        hardware_soak.main(
            [
                "--port",
                str(tmp_path / "tty"),
                "--artifacts",
                str(tmp_path / "passed"),
                "--stages",
                "",
            ]
        )
        == 0
    )

    passed.side_effect = hardware_soak.SoakFailure("failed")
    assert (
        hardware_soak.main(
            [
                "--port",
                str(tmp_path / "tty"),
                "--artifacts",
                str(tmp_path / "failed"),
                "--stages",
                "",
            ]
        )
        == 1
    )
