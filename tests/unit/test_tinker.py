import subprocess
from unittest.mock import MagicMock

import pytest
import typer
from esptool.util import FatalError
from typer.testing import CliRunner

import tinker

try:
    # Older typer/click just re-export click's CliRunner, which mixes
    # stdout/stderr unless told otherwise; newer typer ships its own
    # CliRunner that always separates them and rejects this kwarg.
    runner = CliRunner(mix_stderr=False)
except TypeError:
    runner = CliRunner()


class FakePort:
    def __init__(self, device, description="n/a"):
        self.device = device
        self.description = description

    def __lt__(self, other):
        return self.device < other.device


@pytest.fixture(autouse=True)
def isolate_config(tmp_path, monkeypatch):
    """Point tinker's config file (and ROOT, for relative_to) at a throwaway path."""
    monkeypatch.setattr(tinker, "ROOT", tmp_path)
    monkeypatch.setattr(tinker, "CONFIG_PATH", tmp_path / ".microweaver")
    return tmp_path


# --------------------------------------------------------------------------
# load_config / save_config
# --------------------------------------------------------------------------


def test_load_config_missing_file():
    assert tinker.load_config() == {}


def test_save_and_load_config_roundtrip():
    saved = tinker.save_config(port="/dev/ttyUSB0", baud=9600, path=None)
    assert saved == {"port": "/dev/ttyUSB0", "baud": 9600}
    assert tinker.load_config() == {"port": "/dev/ttyUSB0", "baud": "9600"}


def test_save_config_merges_with_existing():
    tinker.save_config(port="/dev/ttyUSB0")
    tinker.save_config(baud=115200)
    config = tinker.load_config()
    assert config["port"] == "/dev/ttyUSB0"
    assert config["baud"] == "115200"


# --------------------------------------------------------------------------
# print_table
# --------------------------------------------------------------------------


def test_print_table_with_rows(capsys):
    tinker.print_table(["Key", "Value"], [("port", "/dev/ttyUSB0"), ("baud", 9600)])
    out = capsys.readouterr().out
    assert "Key" in out
    assert "port" in out
    assert "/dev/ttyUSB0" in out


def test_print_table_no_rows(capsys):
    tinker.print_table(["Key", "Value"], [])
    out = capsys.readouterr().out
    assert "Key" in out
    assert "Value" in out


# --------------------------------------------------------------------------
# prompt_for_port
# --------------------------------------------------------------------------


def test_prompt_for_port_no_ports_found(mocker):
    mocker.patch.object(tinker.list_ports, "comports", return_value=[])
    with pytest.raises(typer.Exit):
        tinker.prompt_for_port()


def test_prompt_for_port_not_a_tty(mocker):
    mocker.patch.object(
        tinker.list_ports, "comports", return_value=[FakePort("/dev/ttyUSB0")]
    )
    mocker.patch.object(tinker.sys.stdin, "isatty", return_value=False)
    with pytest.raises(typer.Exit):
        tinker.prompt_for_port()


def test_prompt_for_port_single_port(mocker):
    mocker.patch.object(
        tinker.list_ports, "comports", return_value=[FakePort("/dev/ttyUSB0")]
    )
    mocker.patch.object(tinker.sys.stdin, "isatty", return_value=True)
    assert tinker.prompt_for_port() == "/dev/ttyUSB0"


def test_prompt_for_port_multiple_ports_valid_choice(mocker):
    ports = [FakePort("/dev/ttyUSB0", "Board A"), FakePort("/dev/ttyUSB1")]
    mocker.patch.object(tinker.list_ports, "comports", return_value=ports)
    mocker.patch.object(tinker.sys.stdin, "isatty", return_value=True)
    mocker.patch.object(tinker.typer, "prompt", return_value=2)
    assert tinker.prompt_for_port() == "/dev/ttyUSB1"


def test_prompt_for_port_reprompts_on_invalid_choice(mocker):
    ports = [FakePort("/dev/ttyUSB0"), FakePort("/dev/ttyUSB1")]
    mocker.patch.object(tinker.list_ports, "comports", return_value=ports)
    mocker.patch.object(tinker.sys.stdin, "isatty", return_value=True)
    mocker.patch.object(tinker.typer, "prompt", side_effect=[5, 1])
    assert tinker.prompt_for_port() == "/dev/ttyUSB0"


# --------------------------------------------------------------------------
# connect_esp / hard_reset
# --------------------------------------------------------------------------


def test_connect_esp_success(mocker):
    fake_esp = MagicMock()
    mocker.patch.object(tinker, "detect_chip", return_value=fake_esp)
    assert tinker.connect_esp("/dev/ttyUSB0") is fake_esp


def test_connect_esp_failure(mocker):
    mocker.patch.object(tinker, "detect_chip", side_effect=FatalError("no chip"))
    with pytest.raises(typer.Exit):
        tinker.connect_esp("/dev/ttyUSB0")


def test_hard_reset_success(mocker):
    fake_esp = MagicMock()
    mocker.patch.object(tinker, "connect_esp", return_value=fake_esp)
    mock_reset = mocker.patch.object(tinker, "reset_chip")
    tinker.hard_reset("/dev/ttyUSB0")
    mock_reset.assert_called_once_with(fake_esp, "hard-reset")
    fake_esp._port.close.assert_called_once()


def test_hard_reset_failure(mocker):
    fake_esp = MagicMock()
    mocker.patch.object(tinker, "connect_esp", return_value=fake_esp)
    mocker.patch.object(tinker, "reset_chip", side_effect=FatalError("boom"))
    with pytest.raises(typer.Exit):
        tinker.hard_reset("/dev/ttyUSB0")
    fake_esp._port.close.assert_called_once()


# --------------------------------------------------------------------------
# compile_file
# --------------------------------------------------------------------------


def test_compile_file_success(tmp_path, mocker):
    src = tmp_path / "main.py"
    src.write_text("print('hi')")
    dst = tmp_path / "out" / "main.mpy"
    mocker.patch.object(tinker.subprocess, "run", return_value=MagicMock(returncode=0))
    mocker.patch.object(tinker, "ROOT", tmp_path)
    assert tinker.compile_file(src, dst, "1.28", "xtensawin") is True
    assert dst.parent.exists()


def test_compile_file_failure(tmp_path, mocker, capsys):
    src = tmp_path / "main.py"
    src.write_text("print('hi')")
    dst = tmp_path / "out" / "main.mpy"
    mocker.patch.object(
        tinker.subprocess,
        "run",
        return_value=MagicMock(returncode=1, stderr="syntax error"),
    )
    mocker.patch.object(tinker, "ROOT", tmp_path)
    assert tinker.compile_file(src, dst, "1.28", "xtensawin") is False
    assert "syntax error" in capsys.readouterr().err


# --------------------------------------------------------------------------
# build command
# --------------------------------------------------------------------------


@pytest.fixture
def fake_project(tmp_path, mocker):
    """Minimal ROOT with app/config sources + root files, DIST redirected."""
    root = tmp_path / "project"
    dist = tmp_path / "project_dist"
    (root / "app").mkdir(parents=True)
    (root / "config").mkdir(parents=True)
    (root / "app" / "mod.py").write_text("x = 1")
    (root / "config" / "settings.py").write_text("y = 2")
    (root / "_boot.py").write_text("pass")
    (root / "main.py").write_text("pass")
    (root / "boot.py").write_text("pass")
    mocker.patch.object(tinker, "ROOT", root)
    mocker.patch.object(tinker, "DIST", dist)
    return root, dist


def test_build_success_no_device_config(fake_project, mocker):
    root, dist = fake_project
    mocker.patch.object(tinker, "compile_file", return_value=True)
    result = runner.invoke(tinker.app, ["build"])
    assert result.exit_code == 0
    assert (dist / "boot.py").exists()
    assert "device_config.json not found" in result.stdout


def test_build_success_with_device_config(fake_project, mocker):
    root, dist = fake_project
    (root / "device_config.json").write_text("{}")
    mocker.patch.object(tinker, "compile_file", return_value=True)
    result = runner.invoke(tinker.app, ["build"])
    assert result.exit_code == 0
    assert (dist / "device_config.json").exists()


def test_build_reports_compile_errors(fake_project, mocker):
    mocker.patch.object(tinker, "compile_file", return_value=False)
    result = runner.invoke(tinker.app, ["build"])
    assert result.exit_code == 1


def test_build_no_clean_skips_rmtree(fake_project, mocker):
    root, dist = fake_project
    dist.mkdir(parents=True, exist_ok=True)
    marker = dist / "keep.txt"
    marker.write_text("keep me")
    mocker.patch.object(tinker, "compile_file", return_value=True)
    result = runner.invoke(tinker.app, ["build", "--no-clean"])
    assert result.exit_code == 0
    assert marker.exists()


# --------------------------------------------------------------------------
# upload command
# --------------------------------------------------------------------------


def test_upload_missing_mpremote(mocker):
    mocker.patch.object(tinker.shutil, "which", return_value=None)
    result = runner.invoke(tinker.app, ["upload"])
    assert result.exit_code == 1
    assert "mpremote" in result.stderr


def test_upload_path_missing(tmp_path, mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    missing = tmp_path / "nope"
    result = runner.invoke(
        tinker.app, ["upload", "--port", "/dev/ttyUSB0", str(missing)]
    )
    assert result.exit_code == 1
    assert "does not exist" in result.stderr


def test_upload_success(tmp_path, mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mocker.patch.object(tinker.subprocess, "run", return_value=MagicMock(returncode=0))
    src = tmp_path / "dist"
    src.mkdir()
    result = runner.invoke(tinker.app, ["upload", "--port", "/dev/ttyUSB0", str(src)])
    assert result.exit_code == 0
    assert tinker.load_config()["port"] == "/dev/ttyUSB0"


def test_upload_custom_baud_warns(tmp_path, mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mocker.patch.object(tinker.subprocess, "run", return_value=MagicMock(returncode=0))
    src = tmp_path / "dist"
    src.mkdir()
    result = runner.invoke(
        tinker.app,
        ["upload", "--port", "/dev/ttyUSB0", "--baud", "9600", str(src)],
    )
    assert result.exit_code == 0
    assert "ignores --baud" in result.stderr


def test_upload_with_reset_flag(tmp_path, mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mocker.patch.object(tinker.subprocess, "run", return_value=MagicMock(returncode=0))
    mock_reset = mocker.patch.object(tinker, "hard_reset")
    src = tmp_path / "dist"
    src.mkdir()
    result = runner.invoke(
        tinker.app, ["upload", "--port", "/dev/ttyUSB0", "--reset", str(src)]
    )
    assert result.exit_code == 0
    mock_reset.assert_called_once_with("/dev/ttyUSB0")


def test_upload_prompts_for_port_when_missing(tmp_path, mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mocker.patch.object(tinker.subprocess, "run", return_value=MagicMock(returncode=0))
    mocker.patch.object(tinker, "prompt_for_port", return_value="/dev/ttyUSB9")
    src = tmp_path / "dist"
    src.mkdir()
    result = runner.invoke(tinker.app, ["upload", str(src)])
    assert result.exit_code == 0
    assert tinker.load_config()["port"] == "/dev/ttyUSB9"


def test_upload_uses_config_defaults(tmp_path, mocker):
    tinker.save_config(port="/dev/ttyUSB2", baud=115200)
    src = tmp_path / "dist"
    src.mkdir()
    tinker.save_config(path=src)
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mock_run = mocker.patch.object(
        tinker.subprocess, "run", return_value=MagicMock(returncode=0)
    )
    result = runner.invoke(tinker.app, ["upload"])
    assert result.exit_code == 0
    called_cmd = mock_run.call_args[0][0]
    assert "/dev/ttyUSB2" in called_cmd


def test_upload_subprocess_failure(tmp_path, mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mocker.patch.object(tinker.subprocess, "run", return_value=MagicMock(returncode=2))
    src = tmp_path / "dist"
    src.mkdir()
    result = runner.invoke(tinker.app, ["upload", "--port", "/dev/ttyUSB0", str(src)])
    assert result.exit_code == 2


# --------------------------------------------------------------------------
# download command
# --------------------------------------------------------------------------


def test_download_missing_mpremote(mocker):
    mocker.patch.object(tinker.shutil, "which", return_value=None)
    result = runner.invoke(tinker.app, ["download"])
    assert result.exit_code == 1
    assert "mpremote" in result.stderr


def test_download_success(tmp_path, mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mocker.patch.object(tinker.subprocess, "run", return_value=MagicMock(returncode=0))
    dest = tmp_path / "backup"
    result = runner.invoke(
        tinker.app, ["download", "--port", "/dev/ttyUSB0", str(dest)]
    )
    assert result.exit_code == 0
    assert dest.exists()
    assert tinker.load_config()["port"] == "/dev/ttyUSB0"


def test_download_preserves_config_guard(tmp_path, mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    dest = tmp_path / "backup"
    dest.mkdir()
    guard_file = dest / tinker.CONFIG_PATH.name
    guard_file.write_bytes(b"original-config")

    def fake_run(cmd):
        # simulate mpremote clobbering the guarded file
        guard_file.write_bytes(b"clobbered")
        return MagicMock(returncode=0)

    mocker.patch.object(tinker.subprocess, "run", side_effect=fake_run)
    result = runner.invoke(
        tinker.app, ["download", "--port", "/dev/ttyUSB0", str(dest)]
    )
    assert result.exit_code == 0
    assert guard_file.read_bytes() == b"original-config"


def test_download_custom_baud_warns(tmp_path, mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mocker.patch.object(tinker.subprocess, "run", return_value=MagicMock(returncode=0))
    dest = tmp_path / "backup"
    result = runner.invoke(
        tinker.app,
        ["download", "--port", "/dev/ttyUSB0", "--baud", "9600", str(dest)],
    )
    assert "ignores --baud" in result.stderr


def test_download_prompts_for_port(tmp_path, mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mocker.patch.object(tinker.subprocess, "run", return_value=MagicMock(returncode=0))
    mocker.patch.object(tinker, "prompt_for_port", return_value="/dev/ttyUSB9")
    dest = tmp_path / "backup"
    result = runner.invoke(tinker.app, ["download", str(dest)])
    assert result.exit_code == 0
    assert tinker.load_config()["port"] == "/dev/ttyUSB9"


def test_download_subprocess_failure(tmp_path, mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mocker.patch.object(tinker.subprocess, "run", return_value=MagicMock(returncode=3))
    dest = tmp_path / "backup"
    result = runner.invoke(
        tinker.app, ["download", "--port", "/dev/ttyUSB0", str(dest)]
    )
    assert result.exit_code == 3


# --------------------------------------------------------------------------
# config show / set
# --------------------------------------------------------------------------


def test_config_show_empty(mocker):
    result = runner.invoke(tinker.app, ["config", "show"])
    assert result.exit_code == 0
    assert "No config file found" in result.stdout


def test_config_show_with_values():
    tinker.save_config(port="/dev/ttyUSB0", baud=9600)
    result = runner.invoke(tinker.app, ["config", "show"])
    assert result.exit_code == 0
    assert "/dev/ttyUSB0" in result.stdout


def test_config_set_via_flags():
    result = runner.invoke(
        tinker.app, ["config", "set", "--port", "/dev/ttyUSB0", "--baud", "9600"]
    )
    assert result.exit_code == 0
    assert tinker.load_config() == {"port": "/dev/ttyUSB0", "baud": "9600"}


def test_config_set_nothing_to_set_not_tty(mocker):
    mocker.patch.object(tinker.sys.stdin, "isatty", return_value=False)
    result = runner.invoke(tinker.app, ["config", "set"])
    assert result.exit_code == 1
    assert "Nothing to set" in result.stderr


def test_config_set_interactive_prompts(mocker):
    # CliRunner swaps sys.stdin for its own fake stream during invoke(), so
    # isatty must be mocked directly and the command called without the CLI
    # runner to keep the mock in effect.
    mocker.patch.object(tinker.sys.stdin, "isatty", return_value=True)
    mocker.patch.object(
        tinker.typer, "prompt", side_effect=["/dev/ttyUSB5", 9600, str(tinker.DIST)]
    )
    tinker.config_set(port=None, baud=None, path=None)
    assert tinker.load_config()["port"] == "/dev/ttyUSB5"


# --------------------------------------------------------------------------
# device reset / info / ls / tree
# --------------------------------------------------------------------------


def test_device_reset(mocker):
    mock_reset = mocker.patch.object(tinker, "hard_reset")
    result = runner.invoke(tinker.app, ["device", "reset", "--port", "/dev/ttyUSB0"])
    assert result.exit_code == 0
    mock_reset.assert_called_once_with("/dev/ttyUSB0")


def test_device_reset_prompts_for_port(mocker):
    mocker.patch.object(tinker, "prompt_for_port", return_value="/dev/ttyUSB9")
    mock_reset = mocker.patch.object(tinker, "hard_reset")
    result = runner.invoke(tinker.app, ["device", "reset"])
    assert result.exit_code == 0
    mock_reset.assert_called_once_with("/dev/ttyUSB9")


def _fake_esp():
    esp = MagicMock()
    esp.CHIP_NAME = "ESP32"
    esp.get_chip_features.return_value = ["WiFi", "BT"]
    esp.get_crystal_freq.return_value = 40
    esp.get_usb_mode.return_value = None
    esp.read_mac.side_effect = lambda kind: [0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF]
    return esp


def test_device_info_success_no_mpremote(mocker):
    esp = _fake_esp()
    mocker.patch.object(tinker, "connect_esp", return_value=esp)
    mocker.patch.object(tinker, "attach_flash")
    mocker.patch.object(tinker, "get_flash_info", return_value=(0xEF, 0x4016, "4MB"))
    mocker.patch.object(tinker, "reset_chip")
    mocker.patch.object(tinker.shutil, "which", return_value=None)
    result = runner.invoke(tinker.app, ["device", "info", "--port", "/dev/ttyUSB0"])
    assert result.exit_code == 0
    assert "ESP32" in result.stdout
    esp._port.close.assert_called_once()


def test_device_info_with_usb_mode_and_mpremote(mocker):
    esp = _fake_esp()
    esp.get_usb_mode.return_value = "CDC"
    mocker.patch.object(tinker, "connect_esp", return_value=esp)
    mocker.patch.object(tinker, "attach_flash")
    mocker.patch.object(tinker, "get_flash_info", return_value=(0xEF, 0x4016, "4MB"))
    mocker.patch.object(tinker, "reset_chip")
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mocker.patch.object(
        tinker.subprocess,
        "run",
        return_value=MagicMock(returncode=0, stdout="(sysname='esp32')"),
    )
    result = runner.invoke(tinker.app, ["device", "info", "--port", "/dev/ttyUSB0"])
    assert result.exit_code == 0
    assert "CDC" in result.stdout
    assert "esp32" in result.stdout


def test_device_info_mpremote_unresponsive(mocker):
    esp = _fake_esp()
    mocker.patch.object(tinker, "connect_esp", return_value=esp)
    mocker.patch.object(tinker, "attach_flash")
    mocker.patch.object(tinker, "get_flash_info", return_value=(0xEF, 0x4016, "4MB"))
    mocker.patch.object(tinker, "reset_chip")
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mocker.patch.object(
        tinker.subprocess, "run", return_value=MagicMock(returncode=1, stdout="")
    )
    result = runner.invoke(tinker.app, ["device", "info", "--port", "/dev/ttyUSB0"])
    assert result.exit_code == 0
    assert "unavailable (device unresponsive)" in result.stdout


def test_device_info_mpremote_timeout(mocker):
    esp = _fake_esp()
    mocker.patch.object(tinker, "connect_esp", return_value=esp)
    mocker.patch.object(tinker, "attach_flash")
    mocker.patch.object(tinker, "get_flash_info", return_value=(0xEF, 0x4016, "4MB"))
    mocker.patch.object(tinker, "reset_chip")
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mocker.patch.object(
        tinker.subprocess,
        "run",
        side_effect=subprocess.TimeoutExpired(cmd="mpremote", timeout=10),
    )
    result = runner.invoke(tinker.app, ["device", "info", "--port", "/dev/ttyUSB0"])
    assert result.exit_code == 0
    assert "timed out" in result.stdout


def test_device_info_shows_reset_reason(mocker):
    esp = _fake_esp()
    mocker.patch.object(tinker, "connect_esp", return_value=esp)
    mocker.patch.object(tinker, "attach_flash")
    mocker.patch.object(tinker, "get_flash_info", return_value=(0xEF, 0x4016, "4MB"))
    mocker.patch.object(tinker, "reset_chip")
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mock_run = mocker.patch.object(
        tinker.subprocess,
        "run",
        side_effect=[
            MagicMock(returncode=0, stdout="(sysname='esp32')"),
            MagicMock(returncode=0, stdout="Reset reason: power_on\npower_on"),
        ],
    )
    result = runner.invoke(tinker.app, ["device", "info", "--port", "/dev/ttyUSB0"])
    assert result.exit_code == 0
    assert "Reset Reason" in result.stdout
    assert "power_on" in result.stdout
    reset_cmd = mock_run.call_args_list[1][0][0]
    assert reset_cmd[-1] == (
        "from app.services.reset import ResetService; print(ResetService().read())"
    )


def test_device_info_reset_reason_unresponsive(mocker):
    esp = _fake_esp()
    mocker.patch.object(tinker, "connect_esp", return_value=esp)
    mocker.patch.object(tinker, "attach_flash")
    mocker.patch.object(tinker, "get_flash_info", return_value=(0xEF, 0x4016, "4MB"))
    mocker.patch.object(tinker, "reset_chip")
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mocker.patch.object(
        tinker.subprocess,
        "run",
        side_effect=[
            MagicMock(returncode=0, stdout="(sysname='esp32')"),
            MagicMock(returncode=1, stdout=""),
        ],
    )
    result = runner.invoke(tinker.app, ["device", "info", "--port", "/dev/ttyUSB0"])
    assert result.exit_code == 0
    assert "Reset Reason" in result.stdout
    assert "unavailable (device unresponsive)" in result.stdout


def test_device_info_reset_reason_timeout(mocker):
    esp = _fake_esp()
    mocker.patch.object(tinker, "connect_esp", return_value=esp)
    mocker.patch.object(tinker, "attach_flash")
    mocker.patch.object(tinker, "get_flash_info", return_value=(0xEF, 0x4016, "4MB"))
    mocker.patch.object(tinker, "reset_chip")
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mocker.patch.object(
        tinker.subprocess,
        "run",
        side_effect=[
            MagicMock(returncode=0, stdout="(sysname='esp32')"),
            subprocess.TimeoutExpired(cmd="mpremote", timeout=10),
        ],
    )
    result = runner.invoke(tinker.app, ["device", "info", "--port", "/dev/ttyUSB0"])
    assert result.exit_code == 0
    assert "Reset Reason" in result.stdout
    assert "timed out" in result.stdout


def test_device_info_read_failure(mocker):
    esp = _fake_esp()
    mocker.patch.object(tinker, "connect_esp", return_value=esp)
    mocker.patch.object(
        tinker, "attach_flash", side_effect=FatalError("flash unreadable")
    )
    result = runner.invoke(tinker.app, ["device", "info", "--port", "/dev/ttyUSB0"])
    assert result.exit_code == 1
    esp._port.close.assert_called_once()


def test_device_ls_missing_mpremote(mocker):
    mocker.patch.object(tinker.shutil, "which", return_value=None)
    result = runner.invoke(tinker.app, ["device", "ls"])
    assert result.exit_code == 1
    assert "mpremote" in result.stderr


def test_device_ls_success(mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mock_run = mocker.patch.object(
        tinker.subprocess, "run", return_value=MagicMock(returncode=0)
    )
    result = runner.invoke(tinker.app, ["device", "ls", "--port", "/dev/ttyUSB0"])
    assert result.exit_code == 0
    assert mock_run.call_args[0][0][-1] == ":"


def test_device_ls_prompts_for_port_and_failure(mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mocker.patch.object(tinker, "prompt_for_port", return_value="/dev/ttyUSB9")
    mocker.patch.object(tinker.subprocess, "run", return_value=MagicMock(returncode=1))
    result = runner.invoke(tinker.app, ["device", "ls"])
    assert result.exit_code == 1


def test_device_repl_missing_mpremote(mocker):
    mocker.patch.object(tinker.shutil, "which", return_value=None)
    result = runner.invoke(tinker.app, ["device", "repl"])
    assert result.exit_code == 1
    assert "mpremote" in result.stderr


def test_device_repl_success(mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mock_run = mocker.patch.object(
        tinker.subprocess, "run", return_value=MagicMock(returncode=0)
    )
    result = runner.invoke(tinker.app, ["device", "repl", "--port", "/dev/ttyUSB0"])
    assert result.exit_code == 0
    assert mock_run.call_args[0][0] == [
        "mpremote",
        "connect",
        "/dev/ttyUSB0",
        "repl",
    ]


def test_device_repl_prompts_for_port_and_failure(mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mocker.patch.object(tinker, "prompt_for_port", return_value="/dev/ttyUSB9")
    mocker.patch.object(tinker.subprocess, "run", return_value=MagicMock(returncode=1))
    result = runner.invoke(tinker.app, ["device", "repl"])
    assert result.exit_code == 1


def test_device_tree_missing_mpremote(mocker):
    mocker.patch.object(tinker.shutil, "which", return_value=None)
    result = runner.invoke(tinker.app, ["device", "tree"])
    assert result.exit_code == 1
    assert "mpremote" in result.stderr


def test_device_tree_success_with_flags(mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mock_run = mocker.patch.object(
        tinker.subprocess, "run", return_value=MagicMock(returncode=0)
    )
    result = runner.invoke(
        tinker.app,
        ["device", "tree", "--port", "/dev/ttyUSB0", "--size", "--human", "/lib"],
    )
    assert result.exit_code == 0
    cmd = mock_run.call_args[0][0]
    assert "--size" in cmd
    assert "--human" in cmd
    assert cmd[-1] == "/lib"


def test_device_tree_failure(mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mocker.patch.object(tinker.subprocess, "run", return_value=MagicMock(returncode=1))
    result = runner.invoke(tinker.app, ["device", "tree", "--port", "/dev/ttyUSB0"])
    assert result.exit_code == 1


def test_device_rm_missing_mpremote(mocker):
    mocker.patch.object(tinker.shutil, "which", return_value=None)
    result = runner.invoke(tinker.app, ["device", "rm", ":foo.txt"])
    assert result.exit_code == 1
    assert "mpremote" in result.stderr


def test_device_rm_file(mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mock_run = mocker.patch.object(
        tinker.subprocess, "run", return_value=MagicMock(returncode=0)
    )
    result = runner.invoke(
        tinker.app, ["device", "rm", "--port", "/dev/ttyUSB0", ":foo.txt"]
    )
    assert result.exit_code == 0
    assert mock_run.call_args[0][0] == [
        "mpremote",
        "connect",
        "/dev/ttyUSB0",
        "fs",
        "rm",
        ":foo.txt",
    ]


def test_device_rm_recursive(mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mock_run = mocker.patch.object(
        tinker.subprocess, "run", return_value=MagicMock(returncode=0)
    )
    result = runner.invoke(
        tinker.app,
        ["device", "rm", "--port", "/dev/ttyUSB0", "--recursive", ":lib"],
    )
    assert result.exit_code == 0
    assert mock_run.call_args[0][0] == [
        "mpremote",
        "connect",
        "/dev/ttyUSB0",
        "fs",
        "--recursive",
        "rm",
        ":lib",
    ]


def test_device_rm_dir(mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mock_run = mocker.patch.object(
        tinker.subprocess, "run", return_value=MagicMock(returncode=0)
    )
    result = runner.invoke(
        tinker.app, ["device", "rm", "--port", "/dev/ttyUSB0", "--dir", ":empty"]
    )
    assert result.exit_code == 0
    assert mock_run.call_args[0][0] == [
        "mpremote",
        "connect",
        "/dev/ttyUSB0",
        "fs",
        "rmdir",
        ":empty",
    ]


def test_device_rm_prompts_for_port_and_failure(mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mocker.patch.object(tinker, "prompt_for_port", return_value="/dev/ttyUSB9")
    mocker.patch.object(tinker.subprocess, "run", return_value=MagicMock(returncode=1))
    result = runner.invoke(tinker.app, ["device", "rm", ":foo.txt"])
    assert result.exit_code == 1


def test_device_mkdir_missing_mpremote(mocker):
    mocker.patch.object(tinker.shutil, "which", return_value=None)
    result = runner.invoke(tinker.app, ["device", "mkdir", ":lib"])
    assert result.exit_code == 1
    assert "mpremote" in result.stderr


def test_device_mkdir_success(mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mock_run = mocker.patch.object(
        tinker.subprocess, "run", return_value=MagicMock(returncode=0)
    )
    result = runner.invoke(
        tinker.app, ["device", "mkdir", "--port", "/dev/ttyUSB0", ":lib"]
    )
    assert result.exit_code == 0
    assert mock_run.call_args[0][0] == [
        "mpremote",
        "connect",
        "/dev/ttyUSB0",
        "fs",
        "mkdir",
        ":lib",
    ]


def test_device_mkdir_prompts_for_port_and_failure(mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mocker.patch.object(tinker, "prompt_for_port", return_value="/dev/ttyUSB9")
    mocker.patch.object(tinker.subprocess, "run", return_value=MagicMock(returncode=1))
    result = runner.invoke(tinker.app, ["device", "mkdir", ":lib"])
    assert result.exit_code == 1


# --------------------------------------------------------------------------
# port command
# --------------------------------------------------------------------------


def test_list_serial_ports_none_found(mocker):
    mocker.patch.object(tinker.list_ports, "comports", return_value=[])
    result = runner.invoke(tinker.app, ["port"])
    assert result.exit_code == 0
    assert "No serial ports found" in result.stdout


def test_list_serial_ports_found(mocker):
    ports = [FakePort("/dev/ttyUSB0", "USB Serial")]
    mocker.patch.object(tinker.list_ports, "comports", return_value=ports)
    result = runner.invoke(tinker.app, ["port"])
    assert result.exit_code == 0
    assert "/dev/ttyUSB0" in result.stdout
    assert "USB Serial" in result.stdout
