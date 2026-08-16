import hashlib
import json
import re
import shutil
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

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    """Strip Rich/Click color codes so --help assertions survive CI's forced color."""
    return _ANSI_RE.sub("", text)


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
# ota build / ota validate commands
# --------------------------------------------------------------------------


def test_ota_build_single_file(fake_project):
    root, dist = fake_project
    result = runner.invoke(
        tinker.app,
        [
            "ota",
            "build",
            "--version",
            "1.0.0",
            "--base-url",
            "https://cdn.example.com/rel",
            "app/mod.py",
        ],
    )
    assert result.exit_code == 0

    manifest = json.loads((dist / "ota" / "1.0.0" / "manifest.json").read_text())
    assert manifest["version"] == "1.0.0"
    assert manifest["files"] == {
        "app/mod.py": {
            "url": "https://cdn.example.com/rel/app/mod.py",
            "sha256": hashlib.sha256(b"x = 1").hexdigest(),
        }
    }
    copied = dist / "ota" / "1.0.0" / "app" / "mod.py"
    assert copied.read_bytes() == (root / "app" / "mod.py").read_bytes()


def test_ota_build_multiple_files(fake_project):
    root, dist = fake_project
    result = runner.invoke(
        tinker.app,
        [
            "ota",
            "build",
            "--version",
            "1.0.0",
            "--base-url",
            "https://cdn.example.com/rel",
            "app/mod.py",
            "config/settings.py",
        ],
    )
    assert result.exit_code == 0

    manifest = json.loads((dist / "ota" / "1.0.0" / "manifest.json").read_text())
    assert set(manifest["files"]) == {"app/mod.py", "config/settings.py"}
    assert (
        manifest["files"]["app/mod.py"]["sha256"]
        == hashlib.sha256(b"x = 1").hexdigest()
    )
    assert (
        manifest["files"]["config/settings.py"]["sha256"]
        == hashlib.sha256(b"y = 2").hexdigest()
    )
    assert (dist / "ota" / "1.0.0" / "app" / "mod.py").exists()
    assert (dist / "ota" / "1.0.0" / "config" / "settings.py").exists()


def test_ota_build_url_construction_strips_trailing_slash(fake_project):
    _, dist = fake_project
    result = runner.invoke(
        tinker.app,
        [
            "ota",
            "build",
            "--version",
            "1.0.0",
            "--base-url",
            "https://cdn.example.com/rel/",
            "app/mod.py",
        ],
    )
    assert result.exit_code == 0
    manifest = json.loads((dist / "ota" / "1.0.0" / "manifest.json").read_text())
    assert (
        manifest["files"]["app/mod.py"]["url"]
        == "https://cdn.example.com/rel/app/mod.py"
    )


def test_ota_build_missing_source_file(fake_project):
    _, dist = fake_project
    result = runner.invoke(
        tinker.app,
        [
            "ota",
            "build",
            "--version",
            "1.0.0",
            "--base-url",
            "https://cdn.example.com/rel",
            "nope.py",
        ],
    )
    assert result.exit_code == 1
    assert "ERROR" in result.stderr
    assert "nope.py" in result.stderr
    assert not (dist / "ota" / "1.0.0").exists()


def test_ota_build_partial_failure_cleans_up(fake_project):
    _, dist = fake_project
    result = runner.invoke(
        tinker.app,
        [
            "ota",
            "build",
            "--version",
            "1.0.0",
            "--base-url",
            "https://cdn.example.com/rel",
            "app/mod.py",
            "nope.py",
        ],
    )
    assert result.exit_code == 1
    assert not (dist / "ota" / "1.0.0").exists()


def test_ota_build_refuses_existing_version_dir(fake_project):
    _, dist = fake_project
    args = [
        "ota",
        "build",
        "--version",
        "1.0.0",
        "--base-url",
        "https://cdn.example.com/rel",
        "app/mod.py",
    ]
    first = runner.invoke(tinker.app, args)
    assert first.exit_code == 0
    manifest_path = dist / "ota" / "1.0.0" / "manifest.json"
    original = manifest_path.read_text()

    second = runner.invoke(tinker.app, args)

    assert second.exit_code == 1
    assert "already exists" in second.stderr
    assert manifest_path.read_text() == original


def test_ota_build_force_overwrites_existing_version_dir(fake_project):
    _, dist = fake_project
    base_args = [
        "ota",
        "build",
        "--version",
        "1.0.0",
        "--base-url",
        "https://cdn.example.com/rel",
    ]
    first = runner.invoke(tinker.app, base_args + ["app/mod.py"])
    assert first.exit_code == 0

    second = runner.invoke(
        tinker.app, base_args + ["--force", "app/mod.py", "config/settings.py"]
    )

    assert second.exit_code == 0
    manifest = json.loads((dist / "ota" / "1.0.0" / "manifest.json").read_text())
    assert set(manifest["files"]) == {"app/mod.py", "config/settings.py"}


def test_ota_build_manifest_summary_printed(fake_project):
    result = runner.invoke(
        tinker.app,
        [
            "ota",
            "build",
            "--version",
            "1.0.0",
            "--base-url",
            "https://cdn.example.com/rel",
            "app/mod.py",
        ],
    )
    assert result.exit_code == 0
    assert "1 file(s)" in result.stdout
    assert "1.0.0" in result.stdout
    assert "dist" in result.stdout


def _write_manifest(path, manifest):
    path.write_text(json.dumps(manifest))


def test_ota_validate_valid_manifest(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(
        manifest_path,
        {
            "version": "1.0.0",
            "files": {
                "app_main.py": {
                    "url": "https://cdn.example.com/app_main.py",
                    "sha256": "a" * 64,
                }
            },
        },
    )
    result = runner.invoke(tinker.app, ["ota", "validate", str(manifest_path)])
    assert result.exit_code == 0
    assert "manifest OK" in result.stdout


def test_ota_validate_missing_version(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(
        manifest_path,
        {"files": {"a.py": {"url": "https://example.com/a.py", "sha256": "a" * 64}}},
    )
    result = runner.invoke(tinker.app, ["ota", "validate", str(manifest_path)])
    assert result.exit_code == 1
    assert "version" in result.stderr


def test_ota_validate_empty_files(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(manifest_path, {"version": "1.0.0", "files": {}})
    result = runner.invoke(tinker.app, ["ota", "validate", str(manifest_path)])
    assert result.exit_code == 1
    assert "files" in result.stderr


def test_ota_validate_short_form_entry_rejected(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(
        manifest_path,
        {"version": "1.0.0", "files": {"a.py": "https://example.com/a.py"}},
    )
    result = runner.invoke(tinker.app, ["ota", "validate", str(manifest_path)])
    assert result.exit_code == 1
    assert "a.py" in result.stderr
    assert "object form" in result.stderr


def test_ota_validate_malformed_sha256(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(
        manifest_path,
        {
            "version": "1.0.0",
            "files": {"a.py": {"url": "https://example.com/a.py", "sha256": "not-hex"}},
        },
    )
    result = runner.invoke(tinker.app, ["ota", "validate", str(manifest_path)])
    assert result.exit_code == 1
    assert "a.py" in result.stderr
    assert "sha256" in result.stderr


def test_ota_validate_checksum_mismatch_with_files_root(tmp_path):
    files_root = tmp_path / "files"
    files_root.mkdir()
    (files_root / "a.py").write_text("real content")
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(
        manifest_path,
        {
            "version": "1.0.0",
            "files": {"a.py": {"url": "https://example.com/a.py", "sha256": "b" * 64}},
        },
    )
    result = runner.invoke(
        tinker.app,
        ["ota", "validate", str(manifest_path), "--files-root", str(files_root)],
    )
    assert result.exit_code == 1
    assert "mismatch" in result.stderr
    assert "a.py" in result.stderr


def test_ota_validate_checksum_ok_with_files_root(tmp_path):
    files_root = tmp_path / "files"
    files_root.mkdir()
    (files_root / "a.py").write_text("real content")
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(
        manifest_path,
        {
            "version": "1.0.0",
            "files": {
                "a.py": {
                    "url": "https://example.com/a.py",
                    "sha256": hashlib.sha256(b"real content").hexdigest(),
                }
            },
        },
    )
    result = runner.invoke(
        tinker.app,
        ["ota", "validate", str(manifest_path), "--files-root", str(files_root)],
    )
    assert result.exit_code == 0


def test_ota_validate_missing_local_file_with_files_root(tmp_path):
    files_root = tmp_path / "files"
    files_root.mkdir()
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(
        manifest_path,
        {
            "version": "1.0.0",
            "files": {"a.py": {"url": "https://example.com/a.py", "sha256": "a" * 64}},
        },
    )
    result = runner.invoke(
        tinker.app,
        ["ota", "validate", str(manifest_path), "--files-root", str(files_root)],
    )
    assert result.exit_code == 1
    assert "not found" in result.stderr
    assert "a.py" in result.stderr


def test_ota_validate_no_files_root_skips_checksum_check(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(
        manifest_path,
        {
            "version": "1.0.0",
            "files": {"a.py": {"url": "https://example.com/a.py", "sha256": "a" * 64}},
        },
    )
    result = runner.invoke(tinker.app, ["ota", "validate", str(manifest_path)])
    assert result.exit_code == 0


def test_ota_validate_invalid_json(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text("{not json")
    result = runner.invoke(tinker.app, ["ota", "validate", str(manifest_path)])
    assert result.exit_code == 1
    assert "invalid JSON" in result.stderr


def test_ota_validate_multiple_issues_all_reported(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(
        manifest_path,
        {"files": {"a.py": "https://example.com/a.py"}},
    )
    result = runner.invoke(tinker.app, ["ota", "validate", str(manifest_path)])
    assert result.exit_code == 1
    assert "version" in result.stderr
    assert "a.py" in result.stderr


def test_ota_diff_identical_manifests(tmp_path):
    manifest = {
        "version": "1.0.0",
        "files": {
            "app/mod.py": {
                "url": "https://cdn.example.com/1.0.0/app/mod.py",
                "sha256": "a" * 64,
            }
        },
    }
    old_path = tmp_path / "old.json"
    new_path = tmp_path / "new.json"
    _write_manifest(old_path, manifest)
    _write_manifest(new_path, manifest)

    result = runner.invoke(tinker.app, ["ota", "diff", str(old_path), str(new_path)])

    assert result.exit_code == 0
    assert "Version: 1.0.0 (unchanged)" in result.stdout
    assert "No differences." in result.stdout


def test_ota_diff_version_only_change(tmp_path):
    files = {
        "app/mod.py": {
            "url": "https://cdn.example.com/app/mod.py",
            "sha256": "a" * 64,
        }
    }
    old_path = tmp_path / "old.json"
    new_path = tmp_path / "new.json"
    _write_manifest(old_path, {"version": "1.0.0", "files": files})
    _write_manifest(new_path, {"version": "1.0.1", "files": files})

    result = runner.invoke(tinker.app, ["ota", "diff", str(old_path), str(new_path)])

    assert result.exit_code == 1
    assert "Version: 1.0.0 -> 1.0.1" in result.stdout
    assert "No differences." not in result.stdout
    assert "Change" not in result.stdout


def test_ota_diff_classifies_changes(tmp_path):
    old_path = tmp_path / "old.json"
    new_path = tmp_path / "new.json"
    _write_manifest(
        old_path,
        {
            "version": "1.0.0",
            "files": {
                "removed.py": {
                    "url": "https://cdn.example.com/1.0.0/removed.py",
                    "sha256": "a" * 64,
                },
                "content.py": {
                    "url": "https://cdn.example.com/1.0.0/content.py",
                    "sha256": "b" * 64,
                },
                "url.py": {
                    "url": "https://old.example.com/url.py",
                    "sha256": "c" * 64,
                },
            },
        },
    )
    _write_manifest(
        new_path,
        {
            "version": "2.0.0",
            "files": {
                "added.py": {
                    "url": "https://cdn.example.com/2.0.0/added.py",
                    "sha256": "d" * 64,
                },
                "content.py": {
                    "url": "https://cdn.example.com/2.0.0/content.py",
                    "sha256": "e" * 64,
                },
                "url.py": {
                    "url": "https://new.example.com/url.py",
                    "sha256": "C" * 64,
                },
            },
        },
    )

    result = runner.invoke(tinker.app, ["ota", "diff", str(old_path), str(new_path)])

    assert result.exit_code == 1
    assert "Version: 1.0.0 -> 2.0.0" in result.stdout
    for status, path in (
        ("ADDED", "added.py"),
        ("REMOVED", "removed.py"),
        ("CONTENT", "content.py"),
        ("URL", "url.py"),
    ):
        assert status in result.stdout
        assert path in result.stdout


def test_ota_diff_json_output_contains_full_metadata(tmp_path):
    old_path = tmp_path / "old.json"
    new_path = tmp_path / "new.json"
    old_entry = {"url": "https://old.example.com/a.py", "sha256": "a" * 64}
    new_entry = {"url": "https://new.example.com/a.py", "sha256": "b" * 64}
    _write_manifest(old_path, {"version": "1", "files": {"a.py": old_entry}})
    _write_manifest(new_path, {"version": "2", "files": {"a.py": new_entry}})

    result = runner.invoke(
        tinker.app,
        ["ota", "diff", str(old_path), str(new_path), "--json"],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload == {
        "old_version": "1",
        "new_version": "2",
        "version_changed": True,
        "added": [],
        "removed": [],
        "content_changed": [{"path": "a.py", "old": old_entry, "new": new_entry}],
        "url_changed": [],
        "different": True,
    }


def test_ota_diff_invalid_manifests_exit_two_and_report_both(tmp_path):
    old_path = tmp_path / "old.json"
    new_path = tmp_path / "new.json"
    old_path.write_text("{not json")
    _write_manifest(new_path, {"version": "2.0.0", "files": {}})

    result = runner.invoke(tinker.app, ["ota", "diff", str(old_path), str(new_path)])

    assert result.exit_code == 2
    assert "ERROR: OLD: invalid JSON" in result.stderr
    assert "ERROR: NEW: 'files'" in result.stderr


def test_ota_diff_missing_manifest_exits_two(tmp_path):
    missing_path = tmp_path / "missing.json"
    valid_path = tmp_path / "valid.json"
    _write_manifest(
        valid_path,
        {
            "version": "1.0.0",
            "files": {"a.py": {"url": "https://example.com/a.py", "sha256": "a" * 64}},
        },
    )

    result = runner.invoke(
        tinker.app, ["ota", "diff", str(missing_path), str(valid_path)]
    )

    assert result.exit_code == 2
    assert "ERROR: OLD: could not read" in result.stderr


def test_ota_build_help():
    result = runner.invoke(tinker.app, ["ota", "build", "--help"])
    assert result.exit_code == 0
    stdout = _strip_ansi(result.stdout)
    assert "--version" in stdout
    assert "--base-url" in stdout


def test_ota_validate_help():
    result = runner.invoke(tinker.app, ["ota", "validate", "--help"])
    assert result.exit_code == 0
    assert "--files-root" in _strip_ansi(result.stdout)


def test_ota_diff_help():
    result = runner.invoke(tinker.app, ["ota", "diff", "--help"])
    assert result.exit_code == 0
    stdout = _strip_ansi(result.stdout)
    assert "OLD_MANIFEST" in stdout
    assert "NEW_MANIFEST" in stdout
    assert "--json" in stdout


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
# deploy command
# --------------------------------------------------------------------------


def test_deploy_path_missing(tmp_path):
    missing = tmp_path / "nope"
    result = runner.invoke(
        tinker.app, ["deploy", "--port", "/dev/ttyUSB0", str(missing)]
    )
    assert result.exit_code == 1
    assert "does not exist" in result.stderr


def test_deploy_directory_success(tmp_path, mocker):
    fake_transport = FakeDeviceTransport()
    mock_transport_cls = mocker.patch.object(
        tinker, "DeviceTransport", return_value=fake_transport
    )
    src = tmp_path / "dist"
    src.mkdir()
    result = runner.invoke(tinker.app, ["deploy", "--port", "/dev/ttyUSB0", str(src)])
    assert result.exit_code == 0
    assert tinker.load_config()["port"] == "/dev/ttyUSB0"
    assert mock_transport_cls.call_args[0][0] == "/dev/ttyUSB0"
    assert ("put_dir", src, ":") in fake_transport.calls
    assert "[1/1]" in result.stdout
    assert "boot.py" in result.stdout


def test_deploy_single_file_success(tmp_path, mocker):
    fake_transport = FakeDeviceTransport()
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    src = tmp_path / "firmware.mpy"
    src.write_bytes(b"data")
    result = runner.invoke(tinker.app, ["deploy", "--port", "/dev/ttyUSB0", str(src)])
    assert result.exit_code == 0
    assert ("put_file", src, ":firmware.mpy") in fake_transport.calls
    assert f"{src} -> :firmware.mpy" in result.stdout
    assert "[1/1]" not in result.stdout


def test_deploy_custom_baud_warns(tmp_path, mocker):
    fake_transport = FakeDeviceTransport()
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    src = tmp_path / "dist"
    src.mkdir()
    result = runner.invoke(
        tinker.app,
        ["deploy", "--port", "/dev/ttyUSB0", "--baud", "9600", str(src)],
    )
    assert result.exit_code == 0
    assert "ignores --baud" in result.stderr


def test_deploy_with_reset_flag(tmp_path, mocker):
    fake_transport = FakeDeviceTransport()
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    mock_reset = mocker.patch.object(tinker, "hard_reset")
    mocker.patch.object(tinker.time, "sleep")
    src = tmp_path / "dist"
    src.mkdir()
    result = runner.invoke(
        tinker.app, ["deploy", "--port", "/dev/ttyUSB0", "--reset", str(src)]
    )
    assert result.exit_code == 0
    mock_reset.assert_called_once_with("/dev/ttyUSB0")


def test_deploy_retries_raw_repl_race_then_succeeds(tmp_path, mocker):
    """Retry now happens regardless of --reset, unlike the old mpremote path."""
    mocker.patch.object(tinker.time, "sleep")
    fake_transport = FakeDeviceTransport(
        error=tinker.RawReplEntryError("could not enter raw repl"),
        fail_attempts=2,
    )
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    src = tmp_path / "dist"
    src.mkdir()
    result = runner.invoke(tinker.app, ["deploy", "--port", "/dev/ttyUSB0", str(src)])
    assert result.exit_code == 0
    assert fake_transport.attempt == 3
    assert "retrying" in result.stderr


def test_deploy_exhausts_retries(tmp_path, mocker):
    mocker.patch.object(tinker.time, "sleep")
    fake_transport = FakeDeviceTransport(
        raise_on="enter_raw_repl",
        error=tinker.RawReplEntryError("could not enter raw repl"),
    )
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    src = tmp_path / "dist"
    src.mkdir()
    result = runner.invoke(tinker.app, ["deploy", "--port", "/dev/ttyUSB0", str(src)])
    assert result.exit_code == 1
    assert fake_transport.attempt == tinker.UPLOAD_RETRY_ATTEMPTS
    assert "could not enter raw REPL on /dev/ttyUSB0" in result.stderr


def test_deploy_disconnected_device_has_friendly_error(tmp_path, mocker):
    fake_transport = FakeDeviceTransport(
        raise_on="connect",
        error=tinker.SerialException(
            2,
            "could not open port /dev/ttyUSB0: No such file or directory",
        ),
    )
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    src = tmp_path / "dist"
    src.mkdir()

    result = runner.invoke(
        tinker.app,
        ["deploy", "--port", "/dev/ttyUSB0", str(src)],
        color=True,
    )

    assert result.exit_code == 1
    assert "\x1b[31m" in result.stderr
    plain_stderr = _strip_ansi(result.stderr)
    assert "ERROR: Serial port '/dev/ttyUSB0' could not be opened." in plain_stderr
    assert "device may be disconnected" in plain_stderr
    assert "Try this:\n  python tinker.py port" in plain_stderr
    assert "Then retry with '--port <port>'." in plain_stderr
    assert "Traceback" not in plain_stderr


def test_deploy_prompts_for_port_when_missing(tmp_path, mocker):
    fake_transport = FakeDeviceTransport()
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    mocker.patch.object(tinker, "prompt_for_port", return_value="/dev/ttyUSB9")
    src = tmp_path / "dist"
    src.mkdir()
    result = runner.invoke(tinker.app, ["deploy", str(src)])
    assert result.exit_code == 0
    assert tinker.load_config()["port"] == "/dev/ttyUSB9"


def test_deploy_uses_config_defaults(tmp_path, mocker):
    tinker.save_config(port="/dev/ttyUSB2", baud=115200)
    src = tmp_path / "dist"
    src.mkdir()
    tinker.save_config(path=src)
    fake_transport = FakeDeviceTransport()
    mock_transport_cls = mocker.patch.object(
        tinker, "DeviceTransport", return_value=fake_transport
    )
    result = runner.invoke(tinker.app, ["deploy"])
    assert result.exit_code == 0
    assert mock_transport_cls.call_args[0][0] == "/dev/ttyUSB2"


def test_deploy_exec_error(tmp_path, mocker):
    fake_transport = FakeDeviceTransport(
        raise_on="put_dir",
        error=tinker.DeviceExecError("", "OSError: [Errno 28] ENOSPC"),
    )
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    src = tmp_path / "dist"
    src.mkdir()
    result = runner.invoke(tinker.app, ["deploy", "--port", "/dev/ttyUSB0", str(src)])
    assert result.exit_code == 1
    assert "OSError: [Errno 28] ENOSPC" in result.stderr


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


def test_fleet_push_retries_after_reset_race(tmp_path, mocker):
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
        tinker.app,
        ["fleet", "push", "--port", "/dev/ttyUSB0", "--reset", str(src)],
    )
    assert result.exit_code == 0
    assert mock_run.call_count == 2
    assert "retrying" in result.stderr
    assert mock_sleep.call_count == 2


def test_fleet_push_exhausts_retries_after_reset(tmp_path, mocker):
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
        tinker.app,
        ["fleet", "push", "--port", "/dev/ttyUSB0", "--reset", str(src)],
    )
    assert result.exit_code == 1
    assert mock_run.call_count == tinker.UPLOAD_RETRY_ATTEMPTS
    assert "could not enter raw REPL on /dev/ttyUSB0" in result.stderr


def test_fleet_push_non_raw_repl_failure_does_not_retry_after_reset(tmp_path, mocker):
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
        tinker.app,
        ["fleet", "push", "--port", "/dev/ttyUSB0", "--reset", str(src)],
    )
    assert result.exit_code == 1
    assert mock_run.call_count == 1


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
# backup command
# --------------------------------------------------------------------------


def test_backup_success(tmp_path, mocker):
    fake_transport = FakeDeviceTransport()
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    dest = tmp_path / "backup"
    result = runner.invoke(tinker.app, ["backup", "--port", "/dev/ttyUSB0", str(dest)])
    assert result.exit_code == 0
    assert dest.exists()
    assert tinker.load_config()["port"] == "/dev/ttyUSB0"
    assert ("get_dir", ":", dest) in fake_transport.calls


def test_backup_preserves_config_guard(tmp_path, mocker):
    dest = tmp_path / "backup"
    dest.mkdir()
    guard_file = dest / tinker.CONFIG_PATH.name
    guard_file.write_bytes(b"original-config")

    def clobber(local):
        # simulate the backup pulling in and overwriting the guarded file
        guard_file.write_bytes(b"clobbered")

    fake_transport = FakeDeviceTransport(get_dir_side_effect=clobber)
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    result = runner.invoke(tinker.app, ["backup", "--port", "/dev/ttyUSB0", str(dest)])
    assert result.exit_code == 0
    assert guard_file.read_bytes() == b"original-config"


def test_backup_custom_baud_warns(tmp_path, mocker):
    fake_transport = FakeDeviceTransport()
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    dest = tmp_path / "backup"
    result = runner.invoke(
        tinker.app,
        ["backup", "--port", "/dev/ttyUSB0", "--baud", "9600", str(dest)],
    )
    assert "ignores --baud" in result.stderr


def test_backup_prompts_for_port(tmp_path, mocker):
    fake_transport = FakeDeviceTransport()
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    mocker.patch.object(tinker, "prompt_for_port", return_value="/dev/ttyUSB9")
    dest = tmp_path / "backup"
    result = runner.invoke(tinker.app, ["backup", str(dest)])
    assert result.exit_code == 0
    assert tinker.load_config()["port"] == "/dev/ttyUSB9"


def test_backup_raw_repl_failure(tmp_path, mocker):
    mocker.patch.object(tinker.time, "sleep")
    fake_transport = FakeDeviceTransport(
        raise_on="enter_raw_repl",
        error=tinker.RawReplEntryError("could not enter raw repl"),
    )
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    dest = tmp_path / "backup"
    result = runner.invoke(tinker.app, ["backup", "--port", "/dev/ttyUSB0", str(dest)])
    assert result.exit_code == 1
    assert "could not enter raw REPL on /dev/ttyUSB0" in result.stderr


def test_backup_exec_error(tmp_path, mocker):
    fake_transport = FakeDeviceTransport(
        raise_on="get_dir",
        error=tinker.DeviceExecError("", "OSError: device busy"),
    )
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    dest = tmp_path / "backup"
    result = runner.invoke(tinker.app, ["backup", "--port", "/dev/ttyUSB0", str(dest)])
    assert result.exit_code == 1
    assert "OSError: device busy" in result.stderr


# --------------------------------------------------------------------------
# restore command
# --------------------------------------------------------------------------


def test_restore_defaults_to_backup_dir(mocker):
    # typer bakes the Argument default at decoration time (matches backup's
    # own path argument), so it can't be overridden via monkeypatching
    # tinker.BACKUP after import - assert the documented default instead.
    result = runner.invoke(tinker.app, ["restore", "--help"])
    assert result.exit_code == 0
    assert "./backup" in result.stdout


def test_restore_success_with_explicit_path(tmp_path, mocker):
    src = tmp_path / "old-backup"
    src.mkdir()
    fake_transport = FakeDeviceTransport()
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    result = runner.invoke(tinker.app, ["restore", "--port", "/dev/ttyUSB0", str(src)])
    assert result.exit_code == 0
    assert ("put_dir", src, ":") in fake_transport.calls
    assert "Restored" in result.stdout


def test_restore_does_not_persist_path_to_config(tmp_path, mocker):
    src = tmp_path / "old-backup"
    src.mkdir()
    fake_transport = FakeDeviceTransport()
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    result = runner.invoke(tinker.app, ["restore", "--port", "/dev/ttyUSB0", str(src)])
    assert result.exit_code == 0
    assert "path" not in tinker.load_config()


def test_restore_path_missing(tmp_path, mocker):
    missing = tmp_path / "nope"
    result = runner.invoke(
        tinker.app, ["restore", "--port", "/dev/ttyUSB0", str(missing)]
    )
    assert result.exit_code == 1
    assert "does not exist" in result.stderr


def test_restore_with_reset_flag(tmp_path, mocker):
    src = tmp_path / "old-backup"
    src.mkdir()
    fake_transport = FakeDeviceTransport()
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    mock_reset = mocker.patch.object(tinker, "hard_reset")
    mocker.patch.object(tinker.time, "sleep")
    result = runner.invoke(
        tinker.app, ["restore", "--port", "/dev/ttyUSB0", "--reset", str(src)]
    )
    assert result.exit_code == 0
    mock_reset.assert_called_once_with("/dev/ttyUSB0")


def test_restore_custom_baud_warns(tmp_path, mocker):
    src = tmp_path / "old-backup"
    src.mkdir()
    fake_transport = FakeDeviceTransport()
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    result = runner.invoke(
        tinker.app,
        ["restore", "--port", "/dev/ttyUSB0", "--baud", "9600", str(src)],
    )
    assert "ignores --baud" in result.stderr


def test_restore_prompts_for_port(tmp_path, mocker):
    src = tmp_path / "old-backup"
    src.mkdir()
    fake_transport = FakeDeviceTransport()
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    mocker.patch.object(tinker, "prompt_for_port", return_value="/dev/ttyUSB9")
    result = runner.invoke(tinker.app, ["restore", str(src)])
    assert result.exit_code == 0
    assert tinker.load_config()["port"] == "/dev/ttyUSB9"


def test_restore_raw_repl_failure(tmp_path, mocker):
    src = tmp_path / "old-backup"
    src.mkdir()
    mocker.patch.object(tinker.time, "sleep")
    fake_transport = FakeDeviceTransport(
        raise_on="enter_raw_repl",
        error=tinker.RawReplEntryError("could not enter raw repl"),
    )
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    result = runner.invoke(tinker.app, ["restore", "--port", "/dev/ttyUSB0", str(src)])
    assert result.exit_code == 1
    assert "could not enter raw REPL on /dev/ttyUSB0" in result.stderr


def test_restore_exec_error(tmp_path, mocker):
    src = tmp_path / "old-backup"
    src.mkdir()
    fake_transport = FakeDeviceTransport(
        raise_on="put_dir",
        error=tinker.DeviceExecError("", "OSError: device busy"),
    )
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    result = runner.invoke(tinker.app, ["restore", "--port", "/dev/ttyUSB0", str(src)])
    assert result.exit_code == 1
    assert "OSError: device busy" in result.stderr


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


def test_provision_success_via_flags(tmp_path, mocker):
    fake_transport = FakeDeviceTransport()
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
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

    assert ("put_file", config_path, ":device_config.json") in fake_transport.calls
    assert tinker.load_config()["port"] == "/dev/ttyUSB0"


def test_provision_custom_baud_warns(mocker):
    fake_transport = FakeDeviceTransport()
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    result = runner.invoke(
        tinker.app,
        ["provision", "--port", "/dev/ttyUSB0", "--baud", "9600", *PROVISION_FLAGS],
    )
    assert result.exit_code == 0
    assert "ignores --baud" in result.stderr


def test_provision_prompts_for_port_when_missing(mocker):
    fake_transport = FakeDeviceTransport()
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    mocker.patch.object(tinker, "prompt_for_port", return_value="/dev/ttyUSB9")
    result = runner.invoke(tinker.app, ["provision", *PROVISION_FLAGS])
    assert result.exit_code == 0
    assert tinker.load_config()["port"] == "/dev/ttyUSB9"


def test_provision_missing_fields_not_tty(mocker):
    result = runner.invoke(tinker.app, ["provision", "--port", "/dev/ttyUSB0"])
    assert result.exit_code == 1
    assert "no TTY to prompt for" in result.stderr
    assert "--wifi-ssid" in result.stderr


def test_provision_raw_repl_failure(mocker):
    mocker.patch.object(tinker.time, "sleep")
    fake_transport = FakeDeviceTransport(
        raise_on="enter_raw_repl",
        error=tinker.RawReplEntryError("could not enter raw repl"),
    )
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    result = runner.invoke(
        tinker.app,
        ["provision", "--port", "/dev/ttyUSB0", *PROVISION_FLAGS],
    )
    assert result.exit_code == 1
    assert "could not enter raw REPL on /dev/ttyUSB0" in result.stderr


def test_provision_exec_error(mocker):
    fake_transport = FakeDeviceTransport(
        raise_on="put_file",
        error=tinker.DeviceExecError("", "OSError: device busy"),
    )
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    result = runner.invoke(
        tinker.app,
        ["provision", "--port", "/dev/ttyUSB0", *PROVISION_FLAGS],
    )
    assert result.exit_code == 1
    assert "OSError: device busy" in result.stderr


def test_provision_invalid_config_rejected(mocker):
    fake_transport = FakeDeviceTransport()
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
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
    fake_transport = FakeDeviceTransport()
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
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
        api_url=None,
        api_key=None,
        ca_cert=None,
        profile=None,
        name=None,
    )

    written = json.loads((tmp_path / "device_config.json").read_text())
    assert written["wifi_ssid"] == "GivenSSID"
    assert written["wifi_password"] == "prompted-pass"
    assert written["mqtt_broker"] == "example-broker"


def test_provision_masks_existing_secret_default(tmp_path, mocker):
    # An existing device_config.json already has a real secret - it must
    # never be echoed back in the prompt's [default] hint.
    (tmp_path / "device_config.json").write_text(
        json.dumps({"wifi_password": "super-secret", "mqtt_broker": "localhost"})
    )
    mocker.patch.object(tinker.sys.stdin, "isatty", return_value=True)
    fake_transport = FakeDeviceTransport()
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    mock_prompt = mocker.patch.object(
        tinker.typer,
        "prompt",
        side_effect=[
            "GivenSSID",  # wifi_ssid
            "",  # wifi_password - blank keeps the existing secret
            "localhost",  # mqtt_broker
            1883,  # mqtt_port
            "microweaver",  # mqtt_client_id
            "pub/topic",  # mqtt_topic_pub
            "sub/topic",  # mqtt_topic_sub
            "muser",  # mqtt_username
            "new-mqtt-pass",  # mqtt_password - overrides the (empty) default
        ],
    )

    tinker.provision(
        port="/dev/ttyUSB5",
        baud=None,
        wifi_ssid=None,
        wifi_password=None,
        mqtt_broker=None,
        mqtt_port=None,
        mqtt_client_id=None,
        mqtt_topic_pub=None,
        mqtt_topic_sub=None,
        mqtt_username=None,
        mqtt_password=None,
        api_url=None,
        api_key=None,
        ca_cert=None,
        profile=None,
        name=None,
    )

    written = json.loads((tmp_path / "device_config.json").read_text())
    assert written["wifi_password"] == "super-secret"
    assert written["mqtt_password"] == "new-mqtt-pass"

    wifi_password_call = mock_prompt.call_args_list[1]
    assert wifi_password_call.args[0] == "WiFi password [unchanged]"
    assert wifi_password_call.kwargs["default"] == ""
    assert wifi_password_call.kwargs["hide_input"] is True
    assert wifi_password_call.kwargs["show_default"] is False


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


def test_watch_no_source_files(tmp_path, mocker):
    mocker.patch.object(tinker, "ROOT", tmp_path)
    mocker.patch.object(tinker, "DIST", tmp_path / "dist")
    result = runner.invoke(tinker.app, ["watch"])
    assert result.exit_code == 1
    assert "no source files found" in result.stderr


def test_watch_stops_on_keyboard_interrupt_with_no_change(fake_project, mocker):
    mock_sleep = mocker.patch.object(
        tinker.time, "sleep", side_effect=[None, KeyboardInterrupt()]
    )
    mock_build = mocker.patch.object(tinker, "build")
    mock_deploy = mocker.patch.object(tinker, "deploy")
    result = runner.invoke(tinker.app, ["watch"])
    assert result.exit_code == 0
    assert "Stopped watching" in result.stdout
    assert mock_sleep.call_count == 2
    mock_build.assert_not_called()
    mock_deploy.assert_not_called()


def test_watch_rebuilds_and_deploys_on_change(fake_project, mocker):
    root, dist = fake_project

    def touch_then_stop(*args, **kwargs):
        touch_then_stop.calls += 1
        if touch_then_stop.calls == 1:
            (root / "app" / "mod.py").write_text("x = 2")
            return None
        raise KeyboardInterrupt()

    touch_then_stop.calls = 0
    mocker.patch.object(tinker.time, "sleep", side_effect=touch_then_stop)
    mock_build = mocker.patch.object(tinker, "build")
    mock_deploy = mocker.patch.object(tinker, "deploy")
    result = runner.invoke(tinker.app, ["watch", "--port", "/dev/ttyUSB0", "--reset"])
    assert result.exit_code == 0
    assert "Change detected, rebuilding..." in result.stdout
    mock_build.assert_called_once_with(
        micropython="1.28", march="xtensawin", no_clean=False
    )
    mock_deploy.assert_called_once_with(
        port="/dev/ttyUSB0", baud=None, reset=True, path=None
    )


def test_watch_build_failure_skips_deploy(fake_project, mocker):
    root, dist = fake_project

    def touch_then_stop(*args, **kwargs):
        touch_then_stop.calls += 1
        if touch_then_stop.calls == 1:
            (root / "app" / "mod.py").write_text("x = 2")
            return None
        raise KeyboardInterrupt()

    touch_then_stop.calls = 0
    mocker.patch.object(tinker.time, "sleep", side_effect=touch_then_stop)
    mocker.patch.object(tinker, "build", side_effect=typer.Exit(code=1))
    mock_deploy = mocker.patch.object(tinker, "deploy")
    result = runner.invoke(tinker.app, ["watch"])
    assert result.exit_code == 0
    assert "Build failed, skipping deploy." in result.stderr
    mock_deploy.assert_not_called()


def test_watch_deploy_failure_reported(fake_project, mocker):
    root, dist = fake_project

    def touch_then_stop(*args, **kwargs):
        touch_then_stop.calls += 1
        if touch_then_stop.calls == 1:
            (root / "app" / "mod.py").write_text("x = 2")
            return None
        raise KeyboardInterrupt()

    touch_then_stop.calls = 0
    mocker.patch.object(tinker.time, "sleep", side_effect=touch_then_stop)
    mocker.patch.object(tinker, "build")
    mocker.patch.object(tinker, "deploy", side_effect=typer.Exit(code=1))
    result = runner.invoke(tinker.app, ["watch"])
    assert result.exit_code == 0
    assert "Deploy failed." in result.stderr


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
# profile list / show / create / edit / delete / use
# --------------------------------------------------------------------------


def test_profile_list_empty():
    result = runner.invoke(tinker.app, ["profile", "list"])
    assert result.exit_code == 0
    assert "No profiles saved" in result.stdout


def test_profile_create_via_flags():
    result = runner.invoke(
        tinker.app,
        [
            "profile",
            "create",
            "lab",
            "--api-url",
            "https://lab.local",
            "--port",
            "/dev/ttyUSB0",
        ],
    )
    assert result.exit_code == 0
    assert tinker.load_profile("lab") == {
        "api_url": "https://lab.local",
        "port": "/dev/ttyUSB0",
    }
    # 'create' defaults to activating the new profile.
    assert tinker.load_config()["profile"] == "lab"


def test_profile_create_no_activate():
    result = runner.invoke(tinker.app, ["profile", "create", "lab", "--no-activate"])
    assert result.exit_code == 0
    assert tinker.load_config().get("profile") is None
    assert "Created empty profile 'lab'" in result.stdout


def test_profile_create_duplicate_rejected():
    tinker.save_profile("lab", api_url="https://lab.local")
    result = runner.invoke(tinker.app, ["profile", "create", "lab"])
    assert result.exit_code == 1
    assert "already exists" in result.stderr


def test_profile_edit_updates_existing():
    tinker.save_profile("lab", api_url="https://lab.local")
    result = runner.invoke(
        tinker.app, ["profile", "edit", "lab", "--api-key", "secret-key"]
    )
    assert result.exit_code == 0
    assert tinker.load_profile("lab")["api_key"] == "secret-key"
    assert tinker.load_profile("lab")["api_url"] == "https://lab.local"


def test_profile_edit_missing_profile_rejected():
    result = runner.invoke(tinker.app, ["profile", "edit", "ghost", "--port", "x"])
    assert result.exit_code == 1
    assert "no profile named 'ghost'" in result.stderr


def test_profile_edit_nothing_to_set():
    tinker.save_profile("lab", api_url="https://lab.local")
    result = runner.invoke(tinker.app, ["profile", "edit", "lab"])
    assert result.exit_code == 1
    assert "Nothing to set" in result.stderr


def test_profile_show_masks_api_key_by_default():
    tinker.save_profile("lab", api_url="https://lab.local", api_key="secret-key")
    result = runner.invoke(tinker.app, ["profile", "show", "lab"])
    assert result.exit_code == 0
    assert "secret-key" not in result.stdout
    assert "********" in result.stdout


def test_profile_show_reveal():
    tinker.save_profile("lab", api_key="secret-key")
    result = runner.invoke(tinker.app, ["profile", "show", "lab", "--reveal"])
    assert result.exit_code == 0
    assert "secret-key" in result.stdout


def test_profile_show_missing_profile_rejected():
    result = runner.invoke(tinker.app, ["profile", "show", "ghost"])
    assert result.exit_code == 1
    assert "no profile named 'ghost'" in result.stderr


def test_profile_list_marks_active():
    tinker.save_profile("lab", api_url="https://lab.local")
    tinker.save_profile("field", api_url="https://field.local")
    tinker.save_config(profile="lab")
    result = runner.invoke(tinker.app, ["profile", "list"])
    assert result.exit_code == 0
    assert "* lab" in result.stdout
    assert "field" in result.stdout and "* field" not in result.stdout


def test_profile_delete():
    tinker.save_profile("lab", api_url="https://lab.local")
    result = runner.invoke(tinker.app, ["profile", "delete", "lab", "--yes"])
    assert result.exit_code == 0
    assert "Deleted profile 'lab'" in result.stdout
    assert tinker.load_profile("lab") == {}


def test_profile_delete_clears_active_pointer():
    tinker.save_profile("lab", api_url="https://lab.local")
    tinker.save_config(profile="lab")
    runner.invoke(tinker.app, ["profile", "delete", "lab", "--yes"])
    assert tinker.load_config().get("profile") is None


def test_profile_delete_missing_profile_rejected():
    result = runner.invoke(tinker.app, ["profile", "delete", "ghost", "--yes"])
    assert result.exit_code == 1
    assert "no profile named 'ghost'" in result.stderr


def test_profile_delete_declined_confirmation(mocker):
    tinker.save_profile("lab", api_url="https://lab.local")
    mocker.patch.object(tinker.typer, "confirm", return_value=False)
    result = runner.invoke(tinker.app, ["profile", "delete", "lab"])
    assert result.exit_code == 0
    assert tinker.load_profile("lab") != {}


def test_profile_use():
    tinker.save_profile("lab", api_url="https://lab.local")
    result = runner.invoke(tinker.app, ["profile", "use", "lab"])
    assert result.exit_code == 0
    assert "Active profile -> lab" in result.stdout
    assert tinker.load_config()["profile"] == "lab"


def test_profile_use_missing_profile_rejected():
    result = runner.invoke(tinker.app, ["profile", "use", "ghost"])
    assert result.exit_code == 1
    assert "no profile named 'ghost'" in result.stderr


def test_delete_profile_missing_config_file_returns_false():
    assert tinker.delete_profile("ghost") is False


# --------------------------------------------------------------------------
# _resolve_provision_connection_args precedence: CLI > profile > [default]
# --------------------------------------------------------------------------


def test_resolve_provision_args_prefers_cli_over_profile():
    tinker.save_profile("lab", api_url="https://profile.local", port="/dev/ttyUSB1")
    resolved = tinker._resolve_provision_connection_args(
        port="/dev/ttyUSB9",
        baud=None,
        api_url=None,
        api_key=None,
        profile="lab",
        ca_cert=None,
    )
    assert resolved["port"] == "/dev/ttyUSB9"
    assert resolved["api_url"] == "https://profile.local"


def test_resolve_provision_args_prefers_profile_over_default():
    tinker.save_config(api_url="https://default.local", port="/dev/default")
    tinker.save_profile("lab", api_url="https://profile.local")
    resolved = tinker._resolve_provision_connection_args(
        port=None, baud=None, api_url=None, api_key=None, profile="lab", ca_cert=None
    )
    assert resolved["api_url"] == "https://profile.local"
    # profile has no port saved, so it falls through to [default].
    assert resolved["port"] == "/dev/default"


def test_resolve_provision_args_uses_active_profile_when_none_given():
    tinker.save_profile("lab", api_url="https://profile.local")
    tinker.save_config(profile="lab")
    resolved = tinker._resolve_provision_connection_args(
        port=None, baud=None, api_url=None, api_key=None, profile=None, ca_cert=None
    )
    assert resolved["profile"] == "lab"
    assert resolved["api_url"] == "https://profile.local"


def test_resolve_provision_args_profile_ca_cert_overrides_default(tmp_path):
    profile_ca = tmp_path / "profile-ca.pem"
    profile_ca.write_text("profile-pem")
    default_ca = tmp_path / "default-ca.pem"
    default_ca.write_text("default-pem")
    tinker.save_config(ca_cert=str(default_ca))
    tinker.save_profile("lab", ca_cert=str(profile_ca))
    resolved = tinker._resolve_provision_connection_args(
        port=None, baud=None, api_url=None, api_key=None, profile="lab", ca_cert=None
    )
    assert resolved["ca_cert"] == profile_ca


def test_resolve_provision_args_baud_falls_back_to_default_when_no_flag():
    resolved = tinker._resolve_provision_connection_args(
        port=None, baud=None, api_url=None, api_key=None, profile=None, ca_cert=None
    )
    assert resolved["baud"] == tinker.DEFAULT_BAUD


# --------------------------------------------------------------------------
# fetch-ca-cert / profile integration
# --------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolate_home_config_dir(tmp_path, monkeypatch):
    """Keep 'fetch-ca-cert's ~/.microweaver/<profile>/ca.pem writes off the
    real home directory."""
    monkeypatch.setattr(tinker, "HOME_CONFIG_DIR", tmp_path / "home-microweaver")


def test_fetch_ca_cert_saves_cert_and_creates_profile(mocker):
    mocker.patch.object(tinker, "_fetch_ca_cert", return_value="PEM-BEGIN CERTIFICATE")
    result = runner.invoke(
        tinker.app,
        ["fetch-ca-cert", "lab", "--api-url", "https://lab.local"],
    )
    assert result.exit_code == 0
    ca_path = tinker.HOME_CONFIG_DIR / "lab" / "ca.pem"
    assert ca_path.read_text() == "PEM-BEGIN CERTIFICATE"
    assert tinker.load_profile("lab")["api_url"] == "https://lab.local"
    assert tinker.load_config()["profile"] == "lab"


def test_fetch_ca_cert_reuses_saved_profile_api_url(mocker):
    tinker.save_profile("lab", api_url="https://lab.local")
    mock_fetch = mocker.patch.object(
        tinker, "_fetch_ca_cert", return_value="PEM-BEGIN CERTIFICATE"
    )
    result = runner.invoke(tinker.app, ["fetch-ca-cert", "lab"])
    assert result.exit_code == 0
    mock_fetch.assert_called_once_with("https://lab.local")


def test_fetch_ca_cert_no_api_url_anywhere_errors():
    result = runner.invoke(tinker.app, ["fetch-ca-cert", "lab"])
    assert result.exit_code == 1
    assert "--api-url required" in result.stderr


def test_fetch_ca_cert_api_error(mocker):
    mocker.patch.object(
        tinker,
        "_fetch_ca_cert",
        side_effect=tinker.ProvisionApiError("connection refused"),
    )
    result = runner.invoke(
        tinker.app, ["fetch-ca-cert", "lab", "--api-url", "https://lab.local"]
    )
    assert result.exit_code == 1
    assert "connection refused" in result.stderr


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


def test_device_info_success(mocker):
    esp = _fake_esp()
    mocker.patch.object(tinker, "connect_esp", return_value=esp)
    mocker.patch.object(tinker, "attach_flash")
    mocker.patch.object(tinker, "get_flash_info", return_value=(0xEF, 0x4016, "4MB"))
    mocker.patch.object(tinker, "reset_chip")
    fake_transport = FakeDeviceTransport(
        exec_results=["(sysname='esp32')\n", "power_on\n"]
    )
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    result = runner.invoke(tinker.app, ["device", "info", "--port", "/dev/ttyUSB0"])
    assert result.exit_code == 0
    assert "ESP32" in result.stdout
    assert "esp32" in result.stdout
    assert "Reset Reason" in result.stdout
    assert "power_on" in result.stdout
    esp._port.close.assert_called_once()


def test_device_info_prompts_for_port(mocker):
    esp = _fake_esp()
    mocker.patch.object(tinker, "prompt_for_port", return_value="/dev/ttyUSB9")
    mocker.patch.object(tinker, "connect_esp", return_value=esp)
    mocker.patch.object(tinker, "attach_flash")
    mocker.patch.object(tinker, "get_flash_info", return_value=(0xEF, 0x4016, "4MB"))
    mocker.patch.object(tinker, "reset_chip")
    fake_transport = FakeDeviceTransport(
        exec_results=["(sysname='esp32')\n", "power_on\n"]
    )
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    result = runner.invoke(tinker.app, ["device", "info"])
    assert result.exit_code == 0
    tinker.connect_esp.assert_called_once_with("/dev/ttyUSB9")


def test_device_info_with_usb_mode(mocker):
    esp = _fake_esp()
    esp.get_usb_mode.return_value = "CDC"
    mocker.patch.object(tinker, "connect_esp", return_value=esp)
    mocker.patch.object(tinker, "attach_flash")
    mocker.patch.object(tinker, "get_flash_info", return_value=(0xEF, 0x4016, "4MB"))
    mocker.patch.object(tinker, "reset_chip")
    fake_transport = FakeDeviceTransport(
        exec_results=["(sysname='esp32')\n", "power_on\n"]
    )
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    result = runner.invoke(tinker.app, ["device", "info", "--port", "/dev/ttyUSB0"])
    assert result.exit_code == 0
    assert "CDC" in result.stdout
    assert "esp32" in result.stdout


def test_device_info_firmware_fields_unavailable_on_raw_repl_failure(mocker):
    esp = _fake_esp()
    mocker.patch.object(tinker, "connect_esp", return_value=esp)
    mocker.patch.object(tinker, "attach_flash")
    mocker.patch.object(tinker, "get_flash_info", return_value=(0xEF, 0x4016, "4MB"))
    mocker.patch.object(tinker, "reset_chip")
    mocker.patch.object(tinker.time, "sleep")
    fake_transport = FakeDeviceTransport(
        raise_on="enter_raw_repl",
        error=tinker.RawReplEntryError("could not enter raw repl"),
    )
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    result = runner.invoke(tinker.app, ["device", "info", "--port", "/dev/ttyUSB0"])
    assert result.exit_code == 0
    assert "MicroPython" in result.stdout
    assert "Reset Reason" in result.stdout
    assert result.stdout.count("unavailable (device unresponsive)") == 2


def test_device_info_firmware_fields_unavailable_on_exec_error(mocker):
    esp = _fake_esp()
    mocker.patch.object(tinker, "connect_esp", return_value=esp)
    mocker.patch.object(tinker, "attach_flash")
    mocker.patch.object(tinker, "get_flash_info", return_value=(0xEF, 0x4016, "4MB"))
    mocker.patch.object(tinker, "reset_chip")
    fake_transport = FakeDeviceTransport(
        raise_on="exec",
        error=tinker.DeviceExecError("", "OSError: device busy"),
    )
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    result = runner.invoke(tinker.app, ["device", "info", "--port", "/dev/ttyUSB0"])
    assert result.exit_code == 0
    assert result.stdout.count("unavailable (device unresponsive)") == 2


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


def test_device_health_prompts_for_port(mocker):
    mocker.patch.object(tinker, "prompt_for_port", return_value="/dev/ttyUSB9")
    report = {"app_version": "1.0.0", "healthy": True, "checks": {}, "metrics": {}}
    fake_transport = FakeDeviceTransport(exec_results=[json.dumps(report)])
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    result = runner.invoke(tinker.app, ["device", "health"])
    assert result.exit_code == 0
    tinker.prompt_for_port.assert_called_once()


def test_device_health_success(mocker):
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
    fake_transport = FakeDeviceTransport(exec_results=[json.dumps(report)])
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    result = runner.invoke(tinker.app, ["device", "health", "--port", "/dev/ttyUSB0"])
    assert result.exit_code == 0
    assert "1.2.3" in result.stdout
    assert "Check: wifi" in result.stdout
    assert "ok" in result.stdout
    assert "Check: mqtt" in result.stdout
    assert "failed (broker down)" in result.stdout
    assert "12.3" in result.stdout
    assert "Messages Published" in result.stdout
    script = next(c[1] for c in fake_transport.calls if c[0] == "exec")
    assert "HealthCheckService" in script
    assert "WiFiService(setting.WIFI_SSID, setting.WIFI_PASSWORD)" in script


def test_device_health_raw_repl_failure(mocker):
    mocker.patch.object(tinker.time, "sleep")
    fake_transport = FakeDeviceTransport(
        raise_on="enter_raw_repl",
        error=tinker.RawReplEntryError("could not enter raw repl"),
    )
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    result = runner.invoke(tinker.app, ["device", "health", "--port", "/dev/ttyUSB0"])
    assert result.exit_code == 1
    assert "could not enter raw REPL on /dev/ttyUSB0" in result.stderr


def test_device_health_exec_error(mocker):
    fake_transport = FakeDeviceTransport(
        raise_on="exec",
        error=tinker.DeviceExecError("", "OSError: device busy"),
    )
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    result = runner.invoke(tinker.app, ["device", "health", "--port", "/dev/ttyUSB0"])
    assert result.exit_code == 1
    assert "OSError: device busy" in result.stderr


def test_device_health_unparseable_report(mocker):
    fake_transport = FakeDeviceTransport(exec_results=["not json"])
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
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
    """Stand-in for DeviceTransport used by tinker's ls/tree/deploy commands."""

    def __init__(
        self,
        entries=None,
        raise_on=None,
        error=None,
        fail_attempts=0,
        exec_results=None,
        get_dir_side_effect=None,
    ):
        self.entries = entries or []
        self.raise_on = raise_on
        self.error = error
        self.fail_attempts = fail_attempts
        self.attempt = 0
        self.calls = []
        self.exec_results = list(exec_results) if exec_results is not None else None
        self.get_dir_side_effect = get_dir_side_effect

    def connect(self):
        self.attempt += 1
        self.calls.append("connect")
        if self.raise_on == "connect":
            raise self.error

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

    def put_dir(self, local, remote, on_file=None):
        self.calls.append(("put_dir", local, remote))
        if on_file is not None:
            on_file(local / "boot.py", f"{remote}boot.py", 1, 1)
        if self.raise_on == "put_dir":
            raise self.error

    def put_file(self, local, remote, on_start=None):
        self.calls.append(("put_file", local, remote))
        if on_start is not None:
            on_start(local, remote)
        if self.raise_on == "put_file":
            raise self.error

    def get_dir(self, remote, local, on_file=None):
        self.calls.append(("get_dir", remote, local))
        if on_file is not None:
            on_file(f"{remote}boot.py", local / "boot.py", 1, 1)
        if self.get_dir_side_effect is not None:
            self.get_dir_side_effect(local)
        if self.raise_on == "get_dir":
            raise self.error

    def get_file(self, remote, local, on_start=None):
        self.calls.append(("get_file", remote, local))
        if on_start is not None:
            on_start(remote, local)
        if self.raise_on == "get_file":
            raise self.error

    def exec(self, script):
        self.calls.append(("exec", script))
        if self.raise_on == "exec":
            raise self.error
        if self.exec_results is not None:
            return self.exec_results.pop(0)
        return ""

    def rm(self, path):
        self.calls.append(("rm", path))
        if self.raise_on == "rm":
            raise self.error

    def rmdir(self, path):
        self.calls.append(("rmdir", path))
        if self.raise_on == "rmdir":
            raise self.error

    def rm_recursive(self, path):
        self.calls.append(("rm_recursive", path))
        if self.raise_on == "rm_recursive":
            raise self.error

    def mkdir(self, path):
        self.calls.append(("mkdir", path))
        if self.raise_on == "mkdir":
            raise self.error


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


def test_device_test_adapter_rejects_bare_name(mocker):
    result = runner.invoke(tinker.app, ["device", "test-adapter", "DHT22Adapter"])
    assert result.exit_code == 1
    assert "dotted path" in result.stderr


def test_device_test_adapter_success(mocker):
    fake_transport = FakeDeviceTransport(exec_results=["25.3\n"])
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
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
    assert "25.3" in result.stdout
    script = next(c[1] for c in fake_transport.calls if c[0] == "exec")
    assert "from app.adapters.sensors.dht22 import DHT22Adapter" in script
    assert "adapter = DHT22Adapter()" in script
    assert "adapter.setup()" in script
    assert "adapter.deinit()" in script


def test_device_test_adapter_prompts_for_port_and_failure(mocker):
    mocker.patch.object(tinker, "prompt_for_port", return_value="/dev/ttyUSB9")
    fake_transport = FakeDeviceTransport(
        raise_on="exec",
        error=tinker.DeviceExecError("", "AttributeError: no such adapter"),
    )
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    result = runner.invoke(
        tinker.app,
        ["device", "test-adapter", "app.adapters.sensors.dht22.DHT22Adapter"],
    )
    assert result.exit_code == 1


def test_device_test_adapter_raw_repl_failure(mocker):
    mocker.patch.object(tinker.time, "sleep")
    fake_transport = FakeDeviceTransport(
        raise_on="enter_raw_repl",
        error=tinker.RawReplEntryError("could not enter raw repl"),
    )
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
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
    assert result.exit_code == 1
    assert "could not enter raw REPL on /dev/ttyUSB0" in result.stderr


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


def test_device_rm_file(mocker):
    fake_transport = FakeDeviceTransport()
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    result = runner.invoke(
        tinker.app, ["device", "rm", "--port", "/dev/ttyUSB0", ":foo.txt"]
    )
    assert result.exit_code == 0
    assert ("rm", ":foo.txt") in fake_transport.calls


def test_device_rm_recursive(mocker):
    fake_transport = FakeDeviceTransport()
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    result = runner.invoke(
        tinker.app,
        ["device", "rm", "--port", "/dev/ttyUSB0", "--recursive", ":lib"],
    )
    assert result.exit_code == 0
    assert ("rm_recursive", ":lib") in fake_transport.calls


def test_device_rm_dir(mocker):
    fake_transport = FakeDeviceTransport()
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    result = runner.invoke(
        tinker.app, ["device", "rm", "--port", "/dev/ttyUSB0", "--dir", ":empty"]
    )
    assert result.exit_code == 0
    assert ("rmdir", ":empty") in fake_transport.calls


def test_device_rm_prompts_for_port_and_failure(mocker):
    mocker.patch.object(tinker, "prompt_for_port", return_value="/dev/ttyUSB9")
    fake_transport = FakeDeviceTransport(
        raise_on="rm",
        error=tinker.DeviceExecError("", "OSError: [Errno 2] ENOENT"),
    )
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    result = runner.invoke(tinker.app, ["device", "rm", ":foo.txt"])
    assert result.exit_code == 1


def test_device_rm_raw_repl_failure(mocker):
    mocker.patch.object(tinker.time, "sleep")
    fake_transport = FakeDeviceTransport(
        raise_on="enter_raw_repl",
        error=tinker.RawReplEntryError("could not enter raw repl"),
    )
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    result = runner.invoke(
        tinker.app, ["device", "rm", "--port", "/dev/ttyUSB0", ":foo.txt"]
    )
    assert result.exit_code == 1
    assert "could not enter raw REPL on /dev/ttyUSB0" in result.stderr


def test_device_mkdir_success(mocker):
    fake_transport = FakeDeviceTransport()
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    result = runner.invoke(
        tinker.app, ["device", "mkdir", "--port", "/dev/ttyUSB0", ":lib"]
    )
    assert result.exit_code == 0
    assert ("mkdir", ":lib") in fake_transport.calls


def test_device_mkdir_prompts_for_port_and_failure(mocker):
    mocker.patch.object(tinker, "prompt_for_port", return_value="/dev/ttyUSB9")
    fake_transport = FakeDeviceTransport(
        raise_on="mkdir",
        error=tinker.DeviceExecError("", "OSError: [Errno 2] ENOENT"),
    )
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    result = runner.invoke(tinker.app, ["device", "mkdir", ":lib"])
    assert result.exit_code == 1


def test_device_mkdir_raw_repl_failure(mocker):
    mocker.patch.object(tinker.time, "sleep")
    fake_transport = FakeDeviceTransport(
        raise_on="enter_raw_repl",
        error=tinker.RawReplEntryError("could not enter raw repl"),
    )
    mocker.patch.object(tinker, "DeviceTransport", return_value=fake_transport)
    result = runner.invoke(
        tinker.app, ["device", "mkdir", "--port", "/dev/ttyUSB0", ":lib"]
    )
    assert result.exit_code == 1
    assert "could not enter raw REPL on /dev/ttyUSB0" in result.stderr


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


# --------------------------------------------------------------------------
# topics command
# --------------------------------------------------------------------------


def test_topics_errors_when_no_config_found(tmp_path):
    result = runner.invoke(tinker.app, ["topics"])
    assert result.exit_code == 1
    assert "config file not found" in result.stderr


def test_topics_falls_back_to_example_when_device_config_missing(tmp_path):
    (tmp_path / "device_config.json.example").write_text(
        json.dumps(
            {
                "relay_enabled": True,
                "oled_enabled": False,
                "mqtt_topic_pub": "data/sensor/room/temperature",
                "mqtt_topic_sub": ["command/control/room/light"],
            }
        )
    )
    result = runner.invoke(tinker.app, ["topics"])
    assert result.exit_code == 0
    assert "device_config.json.example" in result.stdout
    assert "data/sensor/room/temperature" in result.stdout
    assert "command/control/room/light/relay" in result.stdout
    assert "relay" in result.stdout


def test_topics_prefers_device_config_over_example(tmp_path):
    (tmp_path / "device_config.json.example").write_text(
        json.dumps({"mqtt_topic_pub": "example/pub"})
    )
    (tmp_path / "device_config.json").write_text(
        json.dumps({"mqtt_topic_pub": "real/pub"})
    )
    result = runner.invoke(tinker.app, ["topics"])
    assert result.exit_code == 0
    assert "real/pub" in result.stdout
    assert "example/pub" not in result.stdout
    assert result.stdout.splitlines()[0] == "Config source: device_config.json"


def test_topics_explicit_config_path_outside_root(tmp_path):
    external = tmp_path.parent / "external_config.json"
    external.write_text(json.dumps({"mqtt_topic_pub": "outside/pub"}))
    result = runner.invoke(tinker.app, ["topics", "--config", str(external)])
    assert result.exit_code == 0
    assert f"Config source: {external}" in result.stdout
    assert "outside/pub" in result.stdout
    external.unlink()


def test_topics_routes_relay_and_oled_to_distinct_composed_topics(tmp_path):
    config_path = tmp_path / "device_config.json"
    config_path.write_text(
        json.dumps(
            {
                "relay_enabled": True,
                "oled_enabled": True,
                "dht_enabled": False,
                "mqtt_topic_sub": "command/control/room",
            }
        )
    )
    result = runner.invoke(tinker.app, ["topics"])
    assert result.exit_code == 0
    lines = result.stdout.splitlines()
    relay_line = next(line for line in lines if "command/control/room/relay" in line)
    oled_line = next(line for line in lines if "command/control/room/oled" in line)
    assert "relay" in relay_line
    assert "oled" in oled_line


def test_topics_routes_multiple_pub_adapters_to_distinct_composed_topics(tmp_path):
    config_path = tmp_path / "device_config.json"
    config_path.write_text(
        json.dumps(
            {
                "relay_enabled": False,
                "dht_enabled": True,
                "dht_sensor_type": "dht22",
                "potentiometer_enabled": True,
                "rotary_angle_enabled": True,
                "mqtt_topic_pub": "data/sensor/room",
            }
        )
    )
    result = runner.invoke(tinker.app, ["topics"])
    assert result.exit_code == 0
    lines = result.stdout.splitlines()
    dht_line = next(line for line in lines if "data/sensor/room/dht" in line)
    pot_line = next(line for line in lines if "data/sensor/room/potentiometer" in line)
    rotary_line = next(
        line for line in lines if "data/sensor/room/rotary_angle" in line
    )
    assert "dht" in dht_line
    assert "potentiometer" in pot_line
    assert "rotary_angle" in rotary_line


def test_topics_uses_configured_topic_suffix_override(tmp_path):
    config_path = tmp_path / "device_config.json"
    config_path.write_text(
        json.dumps(
            {
                "relay_enabled": True,
                "relay_topic_suffix": "pump",
                "dht_enabled": False,
                "mqtt_topic_sub": "command/control/room",
            }
        )
    )
    result = runner.invoke(tinker.app, ["topics"])
    assert result.exit_code == 0
    assert "command/control/room/pump" in result.stdout


def test_topics_notes_override_when_no_subscribe_adapters_enabled(tmp_path):
    config_path = tmp_path / "device_config.json"
    config_path.write_text(
        json.dumps(
            {
                "relay_enabled": False,
                "oled_enabled": False,
                "mqtt_topic_sub": ["command/control/room/relay"],
            }
        )
    )
    result = runner.invoke(tinker.app, ["topics"])
    assert result.exit_code == 0
    assert "no subscribe adapters enabled" in result.stdout
    assert "overrides mqtt_topic_sub to []" in result.stdout
    assert "command/control/room/relay" not in result.stdout


def test_topics_no_publish_adapters_enabled(tmp_path):
    config_path = tmp_path / "device_config.json"
    config_path.write_text(json.dumps({"dht_enabled": False, "relay_enabled": True}))
    result = runner.invoke(tinker.app, ["topics"])
    assert result.exit_code == 0
    assert "no publish adapters enabled" in result.stdout


def test_topics_rejects_invalid_config(tmp_path):
    config_path = tmp_path / "device_config.json"
    config_path.write_text(json.dumps({"mqtt_port": "not-a-number"}))
    result = runner.invoke(tinker.app, ["topics"])
    assert result.exit_code == 1
    assert "ERROR" in result.stderr


def test_device_config_errors_when_no_config_found(tmp_path):
    result = runner.invoke(tinker.app, ["device", "config"])
    assert result.exit_code == 1
    assert "config file not found" in result.stderr


def test_device_config_falls_back_to_example_when_device_config_missing(tmp_path):
    (tmp_path / "device_config.json.example").write_text(
        json.dumps({"mqtt_broker": "example-broker", "wifi_password": "secret"})
    )
    result = runner.invoke(tinker.app, ["device", "config"])
    assert result.exit_code == 0
    assert result.stdout.splitlines()[0] == "Config source: device_config.json.example"
    assert "example-broker" in result.stdout


def test_device_config_prefers_device_config_over_example(tmp_path):
    (tmp_path / "device_config.json.example").write_text(
        json.dumps({"mqtt_broker": "example-broker"})
    )
    (tmp_path / "device_config.json").write_text(
        json.dumps({"mqtt_broker": "real-broker"})
    )
    result = runner.invoke(tinker.app, ["device", "config"])
    assert result.exit_code == 0
    assert "real-broker" in result.stdout
    assert "example-broker" not in result.stdout
    assert result.stdout.splitlines()[0] == "Config source: device_config.json"


def test_device_config_explicit_config_path_outside_root(tmp_path):
    external = tmp_path.parent / "external_device_config.json"
    external.write_text(json.dumps({"mqtt_broker": "outside-broker"}))
    result = runner.invoke(tinker.app, ["device", "config", "--config", str(external)])
    assert result.exit_code == 0
    assert f"Config source: {external}" in result.stdout
    assert "outside-broker" in result.stdout
    external.unlink()


def test_device_config_masks_secrets_by_default(tmp_path):
    config_path = tmp_path / "device_config.json"
    config_path.write_text(
        json.dumps(
            {
                "wifi_password": "hunter2",
                "mqtt_password": "swordfish",
                "device_key": "-----BEGIN KEY-----",
                "provisioning_ap_password": "apsecret",
                "mqtt_broker": "plainly-visible",
            }
        )
    )
    result = runner.invoke(tinker.app, ["device", "config"])
    assert result.exit_code == 0
    assert "plainly-visible" in result.stdout
    for secret in ("hunter2", "swordfish", "-----BEGIN KEY-----", "apsecret"):
        assert secret not in result.stdout
    assert result.stdout.count("********") == 4


def test_device_config_reveal_shows_secret_values(tmp_path):
    config_path = tmp_path / "device_config.json"
    config_path.write_text(json.dumps({"wifi_password": "hunter2"}))
    result = runner.invoke(tinker.app, ["device", "config", "--reveal"])
    assert result.exit_code == 0
    assert "hunter2" in result.stdout
    assert "********" not in result.stdout


def test_device_config_leaves_empty_secret_field_blank(tmp_path):
    config_path = tmp_path / "device_config.json"
    config_path.write_text(json.dumps({"wifi_password": ""}))
    result = runner.invoke(tinker.app, ["device", "config"])
    assert result.exit_code == 0
    assert "********" not in result.stdout


def test_device_config_rejects_invalid_json(tmp_path):
    config_path = tmp_path / "device_config.json"
    config_path.write_text("{not valid json")
    result = runner.invoke(tinker.app, ["device", "config"])
    assert result.exit_code == 1
    assert "ERROR" in result.stderr
