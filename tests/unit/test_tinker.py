import json
import shutil
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
# --version flag
# --------------------------------------------------------------------------


def test_version_flag_prints_version_and_exits():
    result = runner.invoke(tinker.app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == f"tinker.py {tinker.VERSION}"


def test_read_version_reads_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[tool.poetry]\nname = "x"\nversion = "9.9.9"\n'
    )
    original = tinker.__file__
    try:
        tinker.__file__ = str(tmp_path / "tinker.py")
        assert tinker._read_version() == "9.9.9"
    finally:
        tinker.__file__ = original


def test_read_version_missing_pyproject(tmp_path):
    original = tinker.__file__
    try:
        tinker.__file__ = str(tmp_path / "tinker.py")
        assert tinker._read_version() == "unknown"
    finally:
        tinker.__file__ = original


def test_read_version_malformed_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text("not valid toml [[[")
    original = tinker.__file__
    try:
        tinker.__file__ = str(tmp_path / "tinker.py")
        assert tinker._read_version() == "unknown"
    finally:
        tinker.__file__ = original


def test_read_version_missing_version_key(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[tool.poetry]\nname = "x"\n')
    original = tinker.__file__
    try:
        tinker.__file__ = str(tmp_path / "tinker.py")
        assert tinker._read_version() == "unknown"
    finally:
        tinker.__file__ = original


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
# clean command
# --------------------------------------------------------------------------


@pytest.fixture
def fake_artifacts(tmp_path, mocker):
    """dist/ and backup/ dirs redirected under tmp_path, both pre-populated."""
    dist = tmp_path / "project_dist"
    backup = tmp_path / "project_backup"
    dist.mkdir()
    (dist / "keep.mpy").write_text("compiled")
    backup.mkdir()
    (backup / "device.py").write_text("saved")
    mocker.patch.object(tinker, "DIST", dist)
    mocker.patch.object(tinker, "BACKUP", backup)
    return dist, backup


def test_clean_removes_dist_only_by_default(fake_artifacts):
    dist, backup = fake_artifacts
    result = runner.invoke(tinker.app, ["clean"])
    assert result.exit_code == 0
    assert not dist.exists()
    assert backup.exists()
    assert "Cleaned dist/" in result.stdout
    assert "backup/" not in result.stdout


def test_clean_removes_backup_with_flag(fake_artifacts):
    dist, backup = fake_artifacts
    result = runner.invoke(tinker.app, ["clean", "--backup"])
    assert result.exit_code == 0
    assert not dist.exists()
    assert not backup.exists()
    assert "Cleaned dist/" in result.stdout
    assert "Cleaned backup/" in result.stdout


def test_clean_nothing_to_clean(tmp_path, mocker):
    mocker.patch.object(tinker, "DIST", tmp_path / "no_dist")
    mocker.patch.object(tinker, "BACKUP", tmp_path / "no_backup")
    result = runner.invoke(tinker.app, ["clean"])
    assert result.exit_code == 0
    assert "Nothing to clean." in result.stdout


def test_clean_backup_flag_but_only_dist_exists(fake_artifacts):
    dist, backup = fake_artifacts
    shutil.rmtree(backup)
    result = runner.invoke(tinker.app, ["clean", "--backup"])
    assert result.exit_code == 0
    assert not dist.exists()
    assert "Cleaned dist/" in result.stdout
    assert "Cleaned backup/" not in result.stdout


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
    mocker.patch.object(
        tinker.subprocess,
        "run",
        return_value=MagicMock(returncode=0, stdout="", stderr=""),
    )
    src = tmp_path / "dist"
    src.mkdir()
    result = runner.invoke(tinker.app, ["upload", "--port", "/dev/ttyUSB0", str(src)])
    assert result.exit_code == 0
    assert tinker.load_config()["port"] == "/dev/ttyUSB0"


def test_upload_custom_baud_warns(tmp_path, mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mocker.patch.object(
        tinker.subprocess,
        "run",
        return_value=MagicMock(returncode=0, stdout="", stderr=""),
    )
    src = tmp_path / "dist"
    src.mkdir()
    result = runner.invoke(
        tinker.app,
        ["upload", "--port", "/dev/ttyUSB0", "--baud", "9600", str(src)],
    )
    assert result.exit_code == 0
    assert "ignores --baud" in result.stderr


def test_upload_resume_uses_resume_connect_prefix(tmp_path, mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mock_run = mocker.patch.object(
        tinker.subprocess,
        "run",
        return_value=MagicMock(returncode=0, stdout="", stderr=""),
    )
    src = tmp_path / "dist"
    src.mkdir()
    result = runner.invoke(
        tinker.app, ["upload", "--port", "/dev/ttyUSB0", "--resume", str(src)]
    )
    assert result.exit_code == 0
    assert mock_run.call_args[0][0][:5] == [
        "mpremote",
        "connect",
        "/dev/ttyUSB0",
        "resume",
        "fs",
    ]


def test_upload_rejects_reset_and_resume_combination(tmp_path, mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    src = tmp_path / "dist"
    src.mkdir()
    result = runner.invoke(
        tinker.app,
        ["upload", "--port", "/dev/ttyUSB0", "--reset", "--resume", str(src)],
    )
    assert result.exit_code == 1
    assert "mutually exclusive" in result.stderr


def test_upload_with_reset_flag(tmp_path, mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mock_run = mocker.patch.object(
        tinker.subprocess,
        "run",
        return_value=MagicMock(returncode=0, stdout="", stderr=""),
    )
    mock_reset = mocker.patch.object(tinker, "hard_reset")
    mocker.patch.object(tinker.time, "sleep")
    src = tmp_path / "dist"
    src.mkdir()
    result = runner.invoke(
        tinker.app, ["upload", "--port", "/dev/ttyUSB0", "--reset", str(src)]
    )
    assert result.exit_code == 0
    mock_reset.assert_called_once_with("/dev/ttyUSB0")
    assert mock_run.call_count == 1


def test_upload_retries_after_reset_race(tmp_path, mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mock_run = mocker.patch.object(
        tinker.subprocess,
        "run",
        side_effect=[
            MagicMock(
                returncode=1,
                stdout="",
                stderr="mpremote.transport.TransportError: could not enter raw repl\n",
            ),
            MagicMock(returncode=0, stdout="", stderr=""),
        ],
    )
    mocker.patch.object(tinker, "hard_reset")
    mock_sleep = mocker.patch.object(tinker.time, "sleep")
    src = tmp_path / "dist"
    src.mkdir()
    result = runner.invoke(
        tinker.app, ["upload", "--port", "/dev/ttyUSB0", "--reset", str(src)]
    )
    assert result.exit_code == 0
    assert mock_run.call_count == 2
    assert "retrying" in result.stderr
    assert mock_sleep.call_count == 2


def test_upload_exhausts_retries_after_reset(tmp_path, mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mock_run = mocker.patch.object(
        tinker.subprocess,
        "run",
        return_value=MagicMock(
            returncode=1,
            stdout="",
            stderr="mpremote.transport.TransportError: could not enter raw repl\n",
        ),
    )
    mocker.patch.object(tinker, "hard_reset")
    mocker.patch.object(tinker.time, "sleep")
    src = tmp_path / "dist"
    src.mkdir()
    result = runner.invoke(
        tinker.app, ["upload", "--port", "/dev/ttyUSB0", "--reset", str(src)]
    )
    assert result.exit_code == 1
    assert mock_run.call_count == tinker.UPLOAD_RETRY_ATTEMPTS


def test_upload_without_reset_does_not_retry(tmp_path, mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mock_run = mocker.patch.object(
        tinker.subprocess,
        "run",
        return_value=MagicMock(
            returncode=1,
            stdout="",
            stderr="mpremote.transport.TransportError: could not enter raw repl\n",
        ),
    )
    src = tmp_path / "dist"
    src.mkdir()
    result = runner.invoke(tinker.app, ["upload", "--port", "/dev/ttyUSB0", str(src)])
    assert result.exit_code == 1
    assert mock_run.call_count == 1


def test_upload_prompts_for_port_when_missing(tmp_path, mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mocker.patch.object(
        tinker.subprocess,
        "run",
        return_value=MagicMock(returncode=0, stdout="", stderr=""),
    )
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
        tinker.subprocess,
        "run",
        return_value=MagicMock(returncode=0, stdout="", stderr=""),
    )
    result = runner.invoke(tinker.app, ["upload"])
    assert result.exit_code == 0
    called_cmd = mock_run.call_args[0][0]
    assert "/dev/ttyUSB2" in called_cmd


def test_upload_subprocess_failure(tmp_path, mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mocker.patch.object(
        tinker.subprocess,
        "run",
        return_value=MagicMock(returncode=2, stdout="", stderr="plain failure\n"),
    )
    src = tmp_path / "dist"
    src.mkdir()
    result = runner.invoke(tinker.app, ["upload", "--port", "/dev/ttyUSB0", str(src)])
    assert result.exit_code == 2


def test_upload_non_raw_repl_failure_does_not_retry_after_reset(tmp_path, mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mock_run = mocker.patch.object(
        tinker.subprocess,
        "run",
        return_value=MagicMock(returncode=2, stdout="", stderr="plain failure\n"),
    )
    mocker.patch.object(tinker, "hard_reset")
    mocker.patch.object(tinker.time, "sleep")
    src = tmp_path / "dist"
    src.mkdir()
    result = runner.invoke(
        tinker.app, ["upload", "--port", "/dev/ttyUSB0", "--reset", str(src)]
    )
    assert result.exit_code == 2
    assert mock_run.call_count == 1


# --------------------------------------------------------------------------
# fleet push command
# --------------------------------------------------------------------------


def test_fleet_push_missing_mpremote(mocker):
    mocker.patch.object(tinker.shutil, "which", return_value=None)
    result = runner.invoke(tinker.app, ["fleet", "push"])
    assert result.exit_code == 1
    assert "mpremote" in result.stderr


def test_fleet_push_no_ports_given_or_detected(mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mocker.patch.object(tinker.list_ports, "comports", return_value=[])
    result = runner.invoke(tinker.app, ["fleet", "push"])
    assert result.exit_code == 1
    assert "no serial ports detected" in result.stderr


def test_fleet_push_path_missing(tmp_path, mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    missing = tmp_path / "nope"
    result = runner.invoke(
        tinker.app,
        ["fleet", "push", "--port", "/dev/ttyUSB0", str(missing)],
    )
    assert result.exit_code == 1
    assert "does not exist" in result.stderr


def test_fleet_push_success_all_ports_ok(tmp_path, mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mock_run = mocker.patch.object(
        tinker.subprocess,
        "run",
        return_value=MagicMock(returncode=0, stdout="", stderr=""),
    )
    src = tmp_path / "dist"
    src.mkdir()
    result = runner.invoke(
        tinker.app,
        [
            "fleet",
            "push",
            "--port",
            "/dev/ttyUSB0",
            "--port",
            "/dev/ttyUSB1",
            str(src),
        ],
    )
    assert result.exit_code == 0
    assert mock_run.call_count == 2
    assert "OK" in result.stdout
    assert "Pushed" in result.stdout


def test_fleet_push_defaults_to_detected_ports(tmp_path, mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    ports = [FakePort("/dev/ttyUSB0"), FakePort("/dev/ttyUSB1")]
    mocker.patch.object(tinker.list_ports, "comports", return_value=ports)
    mock_run = mocker.patch.object(
        tinker.subprocess,
        "run",
        return_value=MagicMock(returncode=0, stdout="", stderr=""),
    )
    src = tmp_path / "dist"
    src.mkdir()
    result = runner.invoke(tinker.app, ["fleet", "push", str(src)])
    assert result.exit_code == 0
    assert mock_run.call_count == 2


def test_fleet_push_defaults_to_dist_path(tmp_path, mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    default_dist = tmp_path / "dist"
    default_dist.mkdir()
    mocker.patch.object(tinker, "DIST", default_dist)
    mock_run = mocker.patch.object(
        tinker.subprocess,
        "run",
        return_value=MagicMock(returncode=0, stdout="", stderr=""),
    )
    result = runner.invoke(tinker.app, ["fleet", "push", "--port", "/dev/ttyUSB0"])
    assert result.exit_code == 0
    assert mock_run.call_count == 1
    called_cmd = mock_run.call_args[0][0]
    assert f"{default_dist}/." in called_cmd


def test_fleet_push_one_device_fails_others_continue(tmp_path, mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mocker.patch.object(
        tinker.subprocess,
        "run",
        side_effect=[
            MagicMock(returncode=1, stdout="", stderr="plain failure\n"),
            MagicMock(returncode=0, stdout="", stderr=""),
        ],
    )
    src = tmp_path / "dist"
    src.mkdir()
    result = runner.invoke(
        tinker.app,
        [
            "fleet",
            "push",
            "--port",
            "/dev/ttyUSB0",
            "--port",
            "/dev/ttyUSB1",
            str(src),
        ],
    )
    assert result.exit_code == 1
    assert "FAILED" in result.stdout
    assert "OK" in result.stdout
    assert "1/2 device(s) failed" in result.stderr


def test_fleet_push_custom_baud_warns(tmp_path, mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mocker.patch.object(
        tinker.subprocess,
        "run",
        return_value=MagicMock(returncode=0, stdout="", stderr=""),
    )
    src = tmp_path / "dist"
    src.mkdir()
    result = runner.invoke(
        tinker.app,
        ["fleet", "push", "--port", "/dev/ttyUSB0", "--baud", "9600", str(src)],
    )
    assert result.exit_code == 0
    assert "ignores --baud" in result.stderr


def test_fleet_push_with_reset_resets_each_device(tmp_path, mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mocker.patch.object(
        tinker.subprocess,
        "run",
        return_value=MagicMock(returncode=0, stdout="", stderr=""),
    )
    mock_reset = mocker.patch.object(tinker, "hard_reset")
    mocker.patch.object(tinker.time, "sleep")
    src = tmp_path / "dist"
    src.mkdir()
    result = runner.invoke(
        tinker.app,
        [
            "fleet",
            "push",
            "--port",
            "/dev/ttyUSB0",
            "--port",
            "/dev/ttyUSB1",
            "--reset",
            str(src),
        ],
    )
    assert result.exit_code == 0
    assert mock_reset.call_args_list == [
        mocker.call("/dev/ttyUSB0"),
        mocker.call("/dev/ttyUSB1"),
    ]


def test_fleet_push_reset_failure_marks_device_failed_and_continues(tmp_path, mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mock_run = mocker.patch.object(
        tinker.subprocess,
        "run",
        return_value=MagicMock(returncode=0, stdout="", stderr=""),
    )
    mocker.patch.object(
        tinker,
        "hard_reset",
        side_effect=[typer.Exit(code=1), None],
    )
    mocker.patch.object(tinker.time, "sleep")
    src = tmp_path / "dist"
    src.mkdir()
    result = runner.invoke(
        tinker.app,
        [
            "fleet",
            "push",
            "--port",
            "/dev/ttyUSB0",
            "--port",
            "/dev/ttyUSB1",
            "--reset",
            str(src),
        ],
    )
    assert result.exit_code == 1
    assert mock_run.call_count == 1
    assert "FAILED" in result.stdout


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

    def fake_run(cmd, **kwargs):
        # simulate mpremote clobbering the guarded file
        guard_file.write_bytes(b"clobbered")
        return MagicMock(returncode=0, stdout="", stderr="")

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


PROVISION_FLAGS = [
    "--wifi-ssid",
    "MySSID",
    "--wifi-password",
    "MyPass",
    "--mqtt-broker",
    "broker.local",
    "--mqtt-port",
    "1884",
    "--mqtt-client-id",
    "device-1",
    "--mqtt-topic-pub",
    "pub/topic",
    "--mqtt-topic-sub",
    "sub/topic",
    "--mqtt-username",
    "muser",
    "--mqtt-password",
    "mpass",
]


# --------------------------------------------------------------------------
# provision command
# --------------------------------------------------------------------------


def test_provision_missing_mpremote(mocker):
    mocker.patch.object(tinker.shutil, "which", return_value=None)
    result = runner.invoke(tinker.app, ["provision"])
    assert result.exit_code == 1
    assert "mpremote" in result.stderr


def test_provision_success_via_flags(tmp_path, mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mock_run = mocker.patch.object(
        tinker.subprocess, "run", return_value=MagicMock(returncode=0)
    )
    result = runner.invoke(
        tinker.app,
        ["provision", "--port", "/dev/ttyUSB0", *PROVISION_FLAGS],
    )
    assert result.exit_code == 0

    config_path = tmp_path / "device_config.json"
    written = json.loads(config_path.read_text())
    assert written["wifi_ssid"] == "MySSID"
    assert written["mqtt_broker"] == "broker.local"
    assert written["mqtt_port"] == 1884

    called_cmd = mock_run.call_args[0][0]
    assert called_cmd == [
        "mpremote",
        "connect",
        "/dev/ttyUSB0",
        "fs",
        "cp",
        str(config_path),
        ":device_config.json",
    ]
    assert tinker.load_config()["port"] == "/dev/ttyUSB0"


def test_provision_custom_baud_warns(mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mocker.patch.object(tinker.subprocess, "run", return_value=MagicMock(returncode=0))
    result = runner.invoke(
        tinker.app,
        ["provision", "--port", "/dev/ttyUSB0", "--baud", "9600", *PROVISION_FLAGS],
    )
    assert result.exit_code == 0
    assert "ignores --baud" in result.stderr


def test_provision_prompts_for_port_when_missing(mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mocker.patch.object(tinker.subprocess, "run", return_value=MagicMock(returncode=0))
    mocker.patch.object(tinker, "prompt_for_port", return_value="/dev/ttyUSB9")
    result = runner.invoke(tinker.app, ["provision", *PROVISION_FLAGS])
    assert result.exit_code == 0
    assert tinker.load_config()["port"] == "/dev/ttyUSB9"


def test_provision_missing_fields_not_tty(mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    result = runner.invoke(tinker.app, ["provision", "--port", "/dev/ttyUSB0"])
    assert result.exit_code == 1
    assert "no TTY to prompt for" in result.stderr
    assert "--wifi-ssid" in result.stderr


def test_provision_subprocess_failure(mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mocker.patch.object(tinker.subprocess, "run", return_value=MagicMock(returncode=2))
    result = runner.invoke(
        tinker.app,
        ["provision", "--port", "/dev/ttyUSB0", *PROVISION_FLAGS],
    )
    assert result.exit_code == 2


def test_provision_invalid_config_rejected(mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mocker.patch.object(tinker.subprocess, "run", return_value=MagicMock(returncode=0))
    flags = list(PROVISION_FLAGS)
    flags[flags.index("1884")] = "999999"  # out of the schema's 1-65535 range
    result = runner.invoke(tinker.app, ["provision", "--port", "/dev/ttyUSB0", *flags])
    assert result.exit_code == 1
    assert "ERROR" in result.stderr


def test_provision_interactive_prompts_fill_only_missing(tmp_path, mocker):
    # CliRunner swaps sys.stdin for its own fake stream during invoke(), so
    # isatty must be mocked directly and the command called without the CLI
    # runner to keep the mock in effect (mirrors test_config_set_interactive).
    (tmp_path / "device_config.json.example").write_text(
        json.dumps({"mqtt_broker": "example-broker"})
    )
    mocker.patch.object(tinker.sys.stdin, "isatty", return_value=True)
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mocker.patch.object(tinker.subprocess, "run", return_value=MagicMock(returncode=0))
    mocker.patch.object(
        tinker.typer,
        "prompt",
        side_effect=[
            "prompted-pass",  # wifi_password
            "example-broker",  # mqtt_broker (default echoed back)
            1884,  # mqtt_port
            "device-1",  # mqtt_client_id
            "pub/topic",  # mqtt_topic_pub
            "sub/topic",  # mqtt_topic_sub
            "muser",  # mqtt_username
            "mpass",  # mqtt_password
        ],
    )

    tinker.provision(
        port="/dev/ttyUSB5",
        baud=None,
        wifi_ssid="GivenSSID",
        wifi_password=None,
        mqtt_broker=None,
        mqtt_port=None,
        mqtt_client_id=None,
        mqtt_topic_pub=None,
        mqtt_topic_sub=None,
        mqtt_username=None,
        mqtt_password=None,
    )

    written = json.loads((tmp_path / "device_config.json").read_text())
    assert written["wifi_ssid"] == "GivenSSID"
    assert written["wifi_password"] == "prompted-pass"
    assert written["mqtt_broker"] == "example-broker"


def test_load_provision_defaults_prefers_existing_config(tmp_path):
    (tmp_path / "device_config.json.example").write_text(
        json.dumps({"mqtt_broker": "from-example"})
    )
    assert tinker._load_provision_defaults() == {"mqtt_broker": "from-example"}

    (tmp_path / "device_config.json").write_text(
        json.dumps({"mqtt_broker": "from-existing-config"})
    )
    assert tinker._load_provision_defaults() == {"mqtt_broker": "from-existing-config"}


def test_load_provision_defaults_no_files(tmp_path):
    assert tinker._load_provision_defaults() == {}


# --------------------------------------------------------------------------
# watch command
# --------------------------------------------------------------------------


def test_watched_files_includes_sources_and_device_config(fake_project):
    root, _ = fake_project
    (root / "device_config.json").write_text("{}")
    files = tinker._watched_files()
    assert root / "app" / "mod.py" in files
    assert root / "config" / "settings.py" in files
    assert root / "_boot.py" in files
    assert root / "main.py" in files
    assert root / "boot.py" in files
    assert root / "device_config.json" in files


def test_watched_files_no_device_config(fake_project):
    root, _ = fake_project
    files = tinker._watched_files()
    assert root / "device_config.json" not in files


def test_scan_mtimes_skips_missing_file(tmp_path):
    present = tmp_path / "present.py"
    present.write_text("x = 1")
    missing = tmp_path / "missing.py"
    snapshot = tinker._scan_mtimes([present, missing])
    assert present in snapshot
    assert missing not in snapshot


def test_watch_missing_mpremote(mocker):
    mocker.patch.object(tinker.shutil, "which", return_value=None)
    result = runner.invoke(tinker.app, ["watch"])
    assert result.exit_code == 1
    assert "mpremote" in result.stderr


def test_watch_no_source_files(tmp_path, mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mocker.patch.object(tinker, "ROOT", tmp_path)
    mocker.patch.object(tinker, "DIST", tmp_path / "dist")
    result = runner.invoke(tinker.app, ["watch"])
    assert result.exit_code == 1
    assert "no source files found" in result.stderr


def test_watch_stops_on_keyboard_interrupt_with_no_change(fake_project, mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mock_sleep = mocker.patch.object(
        tinker.time, "sleep", side_effect=[None, KeyboardInterrupt()]
    )
    mock_build = mocker.patch.object(tinker, "build")
    mock_upload = mocker.patch.object(tinker, "upload")
    result = runner.invoke(tinker.app, ["watch"])
    assert result.exit_code == 0
    assert "Stopped watching" in result.stdout
    assert mock_sleep.call_count == 2
    mock_build.assert_not_called()
    mock_upload.assert_not_called()


def test_watch_rebuilds_and_uploads_on_change(fake_project, mocker):
    root, dist = fake_project
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")

    def touch_then_stop(*args, **kwargs):
        touch_then_stop.calls += 1
        if touch_then_stop.calls == 1:
            (root / "app" / "mod.py").write_text("x = 2")
            return None
        raise KeyboardInterrupt()

    touch_then_stop.calls = 0
    mocker.patch.object(tinker.time, "sleep", side_effect=touch_then_stop)
    mock_build = mocker.patch.object(tinker, "build")
    mock_upload = mocker.patch.object(tinker, "upload")
    result = runner.invoke(tinker.app, ["watch", "--port", "/dev/ttyUSB0", "--reset"])
    assert result.exit_code == 0
    assert "Change detected, rebuilding..." in result.stdout
    mock_build.assert_called_once_with(
        micropython="1.28", march="xtensawin", no_clean=False
    )
    mock_upload.assert_called_once_with(
        port="/dev/ttyUSB0", baud=None, reset=True, path=None
    )


def test_watch_build_failure_skips_upload(fake_project, mocker):
    root, dist = fake_project
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")

    def touch_then_stop(*args, **kwargs):
        touch_then_stop.calls += 1
        if touch_then_stop.calls == 1:
            (root / "app" / "mod.py").write_text("x = 2")
            return None
        raise KeyboardInterrupt()

    touch_then_stop.calls = 0
    mocker.patch.object(tinker.time, "sleep", side_effect=touch_then_stop)
    mocker.patch.object(tinker, "build", side_effect=typer.Exit(code=1))
    mock_upload = mocker.patch.object(tinker, "upload")
    result = runner.invoke(tinker.app, ["watch"])
    assert result.exit_code == 0
    assert "Build failed, skipping upload." in result.stderr
    mock_upload.assert_not_called()


def test_watch_upload_failure_reported(fake_project, mocker):
    root, dist = fake_project
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")

    def touch_then_stop(*args, **kwargs):
        touch_then_stop.calls += 1
        if touch_then_stop.calls == 1:
            (root / "app" / "mod.py").write_text("x = 2")
            return None
        raise KeyboardInterrupt()

    touch_then_stop.calls = 0
    mocker.patch.object(tinker.time, "sleep", side_effect=touch_then_stop)
    mocker.patch.object(tinker, "build")
    mocker.patch.object(tinker, "upload", side_effect=typer.Exit(code=1))
    result = runner.invoke(tinker.app, ["watch"])
    assert result.exit_code == 0
    assert "Upload failed." in result.stderr


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


def test_device_info_prompts_for_port(mocker):
    esp = _fake_esp()
    mocker.patch.object(tinker, "prompt_for_port", return_value="/dev/ttyUSB9")
    mocker.patch.object(tinker, "connect_esp", return_value=esp)
    mocker.patch.object(tinker, "attach_flash")
    mocker.patch.object(tinker, "get_flash_info", return_value=(0xEF, 0x4016, "4MB"))
    mocker.patch.object(tinker, "reset_chip")
    mocker.patch.object(tinker.shutil, "which", return_value=None)
    result = runner.invoke(tinker.app, ["device", "info"])
    assert result.exit_code == 0
    tinker.connect_esp.assert_called_once_with("/dev/ttyUSB9")


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


# --------------------------------------------------------------------------
# device health
# --------------------------------------------------------------------------


def test_device_health_no_mpremote(mocker):
    mocker.patch.object(tinker.shutil, "which", return_value=None)
    result = runner.invoke(tinker.app, ["device", "health", "--port", "/dev/ttyUSB0"])
    assert result.exit_code == 1
    assert "mpremote' not found" in result.stderr


def test_device_health_prompts_for_port(mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mocker.patch.object(tinker, "prompt_for_port", return_value="/dev/ttyUSB9")
    report = {"app_version": "1.0.0", "healthy": True, "checks": {}, "metrics": {}}
    mocker.patch.object(
        tinker.subprocess,
        "run",
        return_value=MagicMock(returncode=0, stdout=json.dumps(report)),
    )
    result = runner.invoke(tinker.app, ["device", "health"])
    assert result.exit_code == 0
    tinker.prompt_for_port.assert_called_once()


def test_device_health_success(mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    report = {
        "app_version": "1.2.3",
        "healthy": False,
        "checks": {
            "wifi": {"healthy": True, "error": None, "checked_at": 100},
            "mqtt": {"healthy": False, "error": "broker down", "checked_at": 100},
        },
        "metrics": {
            "uptime_seconds": 12.345,
            "messages_published": 3,
            "messages_received": 5,
            "errors": 1,
        },
    }
    mock_run = mocker.patch.object(
        tinker.subprocess,
        "run",
        return_value=MagicMock(returncode=0, stdout=json.dumps(report)),
    )
    result = runner.invoke(tinker.app, ["device", "health", "--port", "/dev/ttyUSB0"])
    assert result.exit_code == 0
    assert "1.2.3" in result.stdout
    assert "Check: wifi" in result.stdout
    assert "ok" in result.stdout
    assert "Check: mqtt" in result.stdout
    assert "failed (broker down)" in result.stdout
    assert "12.3" in result.stdout
    assert "Messages Published" in result.stdout
    script = mock_run.call_args[0][0][-1]
    assert "HealthCheckService" in script
    assert "WiFiService(setting.WIFI_SSID, setting.WIFI_PASSWORD)" in script


def test_device_health_mpremote_unresponsive(mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mocker.patch.object(
        tinker.subprocess, "run", return_value=MagicMock(returncode=1, stdout="")
    )
    result = runner.invoke(tinker.app, ["device", "health", "--port", "/dev/ttyUSB0"])
    assert result.exit_code == 1
    assert "unavailable (device unresponsive)" in result.stderr


def test_device_health_mpremote_timeout(mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mocker.patch.object(
        tinker.subprocess,
        "run",
        side_effect=subprocess.TimeoutExpired(cmd="mpremote", timeout=10),
    )
    result = runner.invoke(tinker.app, ["device", "health", "--port", "/dev/ttyUSB0"])
    assert result.exit_code == 1
    assert "timed out" in result.stderr


def test_device_health_unparseable_report(mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mocker.patch.object(
        tinker.subprocess,
        "run",
        return_value=MagicMock(returncode=0, stdout="not json"),
    )
    result = runner.invoke(tinker.app, ["device", "health", "--port", "/dev/ttyUSB0"])
    assert result.exit_code == 1
    assert "could not parse health report" in result.stderr


def test_run_mpremote_cmd_raw_repl_failure_prints_recovery(mocker, capsys):
    mocker.patch.object(
        tinker.subprocess,
        "run",
        return_value=MagicMock(
            returncode=1,
            stdout="",
            stderr=(
                "Traceback (most recent call last):\n"
                "mpremote.transport.TransportError: could not enter raw repl\n"
            ),
        ),
    )
    result = tinker._run_mpremote_cmd(
        ["mpremote", "connect", "/dev/ttyUSB0", "fs", "ls", ":"], "/dev/ttyUSB0"
    )
    captured = capsys.readouterr()
    assert result.returncode == 1
    assert "could not enter raw REPL on /dev/ttyUSB0" in captured.err
    assert "device reset --port /dev/ttyUSB0" in captured.err


class FakeDeviceTransport:
    """Stand-in for DeviceTransport used by tinker's `device ls`/`tree` commands."""

    def __init__(self, entries=None, raise_on=None, error=None, fail_attempts=0):
        self.entries = entries or []
        self.raise_on = raise_on
        self.error = error
        self.fail_attempts = fail_attempts
        self.attempt = 0
        self.calls = []

    def connect(self):
        self.attempt += 1
        self.calls.append("connect")

    def close(self):
        self.calls.append("close")

    def interrupt(self):
        self.calls.append("interrupt")
        if self.raise_on == "interrupt":
            raise self.error

    def enter_raw_repl(self, soft_reset=True):
        self.calls.append(("enter_raw_repl", soft_reset))
        if self.attempt <= self.fail_attempts or self.raise_on == "enter_raw_repl":
            raise self.error

    def ls(self, path):
        self.calls.append(("ls", path))
        if self.raise_on == "ls":
            raise self.error
        if isinstance(self.entries, dict):
            return self.entries.get(path, [])
        return self.entries

    def exit_raw_repl(self):
        self.calls.append("exit_raw_repl")


def test_device_ls_success(mocker):
    fake_transport = FakeDeviceTransport(
        entries=[("boot.py", 1024, False), ("lib", 0, True)]
    )
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    result = runner.invoke(tinker.app, ["device", "ls", "--port", "/dev/ttyUSB0"])
    assert result.exit_code == 0
    assert "boot.py" in result.stdout
    assert "lib/" in result.stdout
    assert fake_transport.calls == [
        "connect",
        "interrupt",
        ("enter_raw_repl", False),
        ("ls", ":"),
        "exit_raw_repl",
        "close",
    ]


def test_device_ls_retries_raw_repl_race_then_succeeds(mocker):
    mocker.patch.object(tinker.time, "sleep")
    fake_transport = FakeDeviceTransport(
        entries=[("boot.py", 1024, False)],
        error=tinker.RawReplEntryError("could not enter raw repl"),
        fail_attempts=2,
    )
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    result = runner.invoke(tinker.app, ["device", "ls", "--port", "/dev/ttyUSB0"])
    assert result.exit_code == 0
    assert "boot.py" in result.stdout
    assert fake_transport.attempt == 3


def test_device_ls_prompts_for_port_and_raw_repl_failure(mocker):
    mocker.patch.object(tinker, "prompt_for_port", return_value="/dev/ttyUSB9")
    mocker.patch.object(tinker.time, "sleep")
    fake_transport = FakeDeviceTransport(
        raise_on="enter_raw_repl",
        error=tinker.RawReplEntryError("could not enter raw repl"),
    )
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    result = runner.invoke(tinker.app, ["device", "ls"])
    assert result.exit_code == 1
    assert (
        f"could not enter raw REPL on /dev/ttyUSB9 after "
        f"{tinker.UPLOAD_RETRY_ATTEMPTS} attempts" in result.stderr
    )
    assert "device reset --port /dev/ttyUSB9" in result.stderr
    assert fake_transport.attempt == tinker.UPLOAD_RETRY_ATTEMPTS


def test_device_ls_exec_error(mocker):
    fake_transport = FakeDeviceTransport(
        raise_on="ls",
        error=tinker.DeviceExecError("", "OSError: [Errno 2] ENOENT"),
    )
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    result = runner.invoke(tinker.app, ["device", "ls", "--port", "/dev/ttyUSB0"])
    assert result.exit_code == 1
    assert "OSError: [Errno 2] ENOENT" in result.stderr


def test_device_test_adapter_missing_mpremote(mocker):
    mocker.patch.object(tinker.shutil, "which", return_value=None)
    result = runner.invoke(
        tinker.app,
        ["device", "test-adapter", "app.adapters.sensors.dht22.DHT22Adapter"],
    )
    assert result.exit_code == 1
    assert "mpremote" in result.stderr


def test_device_test_adapter_rejects_bare_name(mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    result = runner.invoke(tinker.app, ["device", "test-adapter", "DHT22Adapter"])
    assert result.exit_code == 1
    assert "dotted path" in result.stderr


def test_device_test_adapter_success(mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mock_run = mocker.patch.object(
        tinker.subprocess, "run", return_value=MagicMock(returncode=0)
    )
    result = runner.invoke(
        tinker.app,
        [
            "device",
            "test-adapter",
            "app.adapters.sensors.dht22.DHT22Adapter",
            "--port",
            "/dev/ttyUSB0",
        ],
    )
    assert result.exit_code == 0
    cmd = mock_run.call_args[0][0]
    assert cmd[:4] == ["mpremote", "connect", "/dev/ttyUSB0", "exec"]
    script = cmd[-1]
    assert "from app.adapters.sensors.dht22 import DHT22Adapter" in script
    assert "adapter = DHT22Adapter()" in script
    assert "adapter.setup()" in script
    assert "adapter.deinit()" in script


def test_device_test_adapter_prompts_for_port_and_failure(mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mocker.patch.object(tinker, "prompt_for_port", return_value="/dev/ttyUSB9")
    mocker.patch.object(tinker.subprocess, "run", return_value=MagicMock(returncode=1))
    result = runner.invoke(
        tinker.app,
        ["device", "test-adapter", "app.adapters.sensors.dht22.DHT22Adapter"],
    )
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


def test_device_repl_raw_repl_failure_prints_recovery(mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mocker.patch.object(
        tinker.subprocess,
        "run",
        return_value=MagicMock(
            returncode=1,
            stderr="mpremote.transport.TransportError: could not enter raw repl\n",
        ),
    )
    result = runner.invoke(tinker.app, ["device", "repl", "--port", "/dev/ttyUSB0"])
    assert result.exit_code == 1
    assert "could not enter raw REPL on /dev/ttyUSB0" in result.stderr
    assert "device reset --port /dev/ttyUSB0" in result.stderr


@pytest.mark.parametrize("subcommand", ["logs", "monitor"])
def test_device_logs_missing_mpremote(subcommand, mocker):
    mocker.patch.object(tinker.shutil, "which", return_value=None)
    result = runner.invoke(tinker.app, ["device", subcommand])
    assert result.exit_code == 1
    assert "mpremote" in result.stderr


@pytest.mark.parametrize("subcommand", ["logs", "monitor"])
def test_device_logs_success(subcommand, mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mock_run = mocker.patch.object(
        tinker.subprocess, "run", return_value=MagicMock(returncode=0)
    )
    result = runner.invoke(tinker.app, ["device", subcommand, "--port", "/dev/ttyUSB0"])
    assert result.exit_code == 0
    assert mock_run.call_args[0][0] == [
        "mpremote",
        "connect",
        "/dev/ttyUSB0",
        "repl",
    ]


@pytest.mark.parametrize("subcommand", ["logs", "monitor"])
def test_device_logs_with_capture(subcommand, mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mock_run = mocker.patch.object(
        tinker.subprocess, "run", return_value=MagicMock(returncode=0)
    )
    result = runner.invoke(
        tinker.app,
        ["device", subcommand, "--port", "/dev/ttyUSB0", "--capture", "out.log"],
    )
    assert result.exit_code == 0
    assert mock_run.call_args[0][0] == [
        "mpremote",
        "connect",
        "/dev/ttyUSB0",
        "repl",
        "--capture",
        "out.log",
    ]


@pytest.mark.parametrize("subcommand", ["logs", "monitor"])
def test_device_logs_prompts_for_port_and_failure(subcommand, mocker):
    mocker.patch.object(tinker.shutil, "which", return_value="/usr/bin/mpremote")
    mocker.patch.object(tinker, "prompt_for_port", return_value="/dev/ttyUSB9")
    mocker.patch.object(tinker.subprocess, "run", return_value=MagicMock(returncode=1))
    result = runner.invoke(tinker.app, ["device", subcommand])
    assert result.exit_code == 1


def test_device_tree_recurses_into_subdirectories(mocker):
    fake_transport = FakeDeviceTransport(
        entries={
            "/": [("boot.py", 100, False), ("lib", 0, True)],
            "/lib": [("foo.py", 50, False)],
        }
    )
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    result = runner.invoke(tinker.app, ["device", "tree", "--port", "/dev/ttyUSB0"])
    assert result.exit_code == 0
    assert result.stdout == (":/\n" "├── boot.py\n" "└── lib\n" "    └── foo.py\n")


def test_device_tree_with_size_flag(mocker):
    fake_transport = FakeDeviceTransport(entries={"/": [("boot.py", 1024, False)]})
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    result = runner.invoke(
        tinker.app, ["device", "tree", "--port", "/dev/ttyUSB0", "--size"]
    )
    assert result.exit_code == 0
    assert "[     1024]  boot.py" in result.stdout


def test_human_size_bytes():
    assert tinker._human_size(500) == "500"


def test_human_size_kilobytes():
    assert tinker._human_size(2048) == "2.0K"


def test_human_size_megabytes():
    assert tinker._human_size(2 * 1024**2) == "2.0M"


def test_human_size_gigabytes():
    assert tinker._human_size(3 * 1024**3) == "3.0G"


def test_human_size_terabytes():
    assert tinker._human_size(5 * 1024**4) == "5.0T"


def test_device_tree_with_human_flag(mocker):
    fake_transport = FakeDeviceTransport(
        entries={"/": [("firmware.bin", 2_097_152, False)]}
    )
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    result = runner.invoke(
        tinker.app, ["device", "tree", "--port", "/dev/ttyUSB0", "--human"]
    )
    assert result.exit_code == 0
    assert "[  2.0M]  firmware.bin" in result.stdout


def test_device_tree_empty_dir_hides_size_column(mocker):
    fake_transport = FakeDeviceTransport(
        entries={"/": [("lib", 0, True), ("empty", 0, True)]}
    )
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    result = runner.invoke(
        tinker.app, ["device", "tree", "--port", "/dev/ttyUSB0", "--size"]
    )
    assert result.exit_code == 0
    assert "[" not in result.stdout.splitlines()[1]


def test_device_tree_starts_at_given_path(mocker):
    fake_transport = FakeDeviceTransport(entries={"lib": [("foo.py", 10, False)]})
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    result = runner.invoke(
        tinker.app, ["device", "tree", "--port", "/dev/ttyUSB0", ":lib"]
    )
    assert result.exit_code == 0
    assert result.stdout == ":lib\n└── foo.py\n"


def test_device_tree_raw_repl_failure(mocker):
    mocker.patch.object(tinker, "prompt_for_port", return_value="/dev/ttyUSB9")
    mocker.patch.object(tinker.time, "sleep")
    fake_transport = FakeDeviceTransport(
        raise_on="enter_raw_repl",
        error=tinker.RawReplEntryError("could not enter raw repl"),
    )
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    result = runner.invoke(tinker.app, ["device", "tree"])
    assert result.exit_code == 1
    assert "could not enter raw REPL on /dev/ttyUSB9" in result.stderr


def test_device_tree_exec_error(mocker):
    fake_transport = FakeDeviceTransport(
        raise_on="ls",
        error=tinker.DeviceExecError("", "OSError: [Errno 20] ENOTDIR"),
    )
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    result = runner.invoke(tinker.app, ["device", "tree", "--port", "/dev/ttyUSB0"])
    assert result.exit_code == 1
    assert "OSError: [Errno 20] ENOTDIR" in result.stderr


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
