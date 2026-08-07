from unittest.mock import MagicMock

from app.services.ota import OtaService


def make_response(status_code=200, json_data=None, text=""):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_data or {}
    response.text = text
    return response


def test_check_for_update_skips_without_manifest_url():
    service = OtaService(manifest_url="")

    result = service.check_for_update()

    assert result is None


def test_check_for_update_returns_manifest_on_success(mocker):
    mock_get = mocker.patch("app.services.ota.urequests.get")
    mock_get.return_value = make_response(200, {"version": "1.2.3", "files": {}})

    service = OtaService(manifest_url="https://api.example.com/manifest.json")

    result = service.check_for_update()

    mock_get.assert_called_once_with("https://api.example.com/manifest.json")
    assert result == {"version": "1.2.3", "files": {}}
    mock_get.return_value.close.assert_called_once_with()


def test_check_for_update_returns_none_on_non_200_response(mocker):
    mock_get = mocker.patch("app.services.ota.urequests.get")
    mock_get.return_value = make_response(404, {})

    service = OtaService(manifest_url="https://api.example.com/manifest.json")

    result = service.check_for_update()

    assert result is None
    mock_get.return_value.close.assert_called_once_with()


def test_check_for_update_returns_none_when_get_raises(mocker):
    mock_get = mocker.patch("app.services.ota.urequests.get")
    mock_get.side_effect = OSError("network unreachable")

    service = OtaService(manifest_url="https://api.example.com/manifest.json")

    result = service.check_for_update()

    assert result is None


def test_is_update_available_false_without_manifest():
    service = OtaService()

    assert service.is_update_available(None) is False


def test_is_update_available_false_without_version_in_manifest():
    service = OtaService()

    assert service.is_update_available({}) is False


def test_is_update_available_false_when_versions_match():
    setting = MagicMock()
    setting.APP_VERSION = "1.2.3"
    service = OtaService(setting=setting)

    assert service.is_update_available({"version": "1.2.3"}) is False


def test_is_update_available_true_when_versions_differ():
    setting = MagicMock()
    setting.APP_VERSION = "1.2.3"
    service = OtaService(setting=setting)

    assert service.is_update_available({"version": "1.3.0"}) is True


def test_is_update_available_true_without_setting():
    service = OtaService()

    assert service.is_update_available({"version": "1.3.0"}) is True


def test_apply_payload_writes_file(tmp_path):
    target = tmp_path / "main.py"
    service = OtaService()

    result = service.apply_payload(str(target), "print('hi')")

    assert result is True
    assert target.read_text() == "print('hi')"


def test_apply_payload_returns_false_on_write_failure(mocker):
    service = OtaService()
    mocker.patch.object(service, "write_file", side_effect=OSError("disk full"))

    result = service.apply_payload("main.py", "content")

    assert result is False


def test_download_file_writes_response_body(mocker, tmp_path):
    mock_get = mocker.patch("app.services.ota.urequests.get")
    mock_get.return_value = make_response(200, text="print('hi')")
    target = tmp_path / "main.py"

    service = OtaService()
    result = service.download_file("https://api.example.com/main.py", str(target))

    assert result is True
    assert target.read_text() == "print('hi')"
    mock_get.return_value.close.assert_called_once_with()


def test_download_file_accepts_payload_matching_checksum(mocker, tmp_path):
    mock_get = mocker.patch("app.services.ota.urequests.get")
    mock_get.return_value = make_response(200, text="print('hi')")
    target = tmp_path / "main.py"
    expected_sha256 = "c2d0a5e0790d97a015387a995c0d0b5eb3e88138466586fc980787c9b1731eb8"

    service = OtaService()
    result = service.download_file(
        "https://api.example.com/main.py", str(target), expected_sha256
    )

    assert result is True
    assert target.read_text() == "print('hi')"


def test_download_file_rejects_payload_with_checksum_mismatch(mocker, tmp_path):
    mock_get = mocker.patch("app.services.ota.urequests.get")
    mock_get.return_value = make_response(200, text="tampered payload")
    target = tmp_path / "main.py"

    service = OtaService()
    result = service.download_file(
        "https://api.example.com/main.py", str(target), "0" * 64
    )

    assert result is False
    assert not target.exists()


def test_download_file_returns_false_when_checksum_computation_fails(mocker, tmp_path):
    mock_get = mocker.patch("app.services.ota.urequests.get")
    mock_get.return_value = make_response(200, text="print('hi')")
    target = tmp_path / "main.py"

    service = OtaService()
    mocker.patch.object(service, "write_file")

    result = service.download_file(
        "https://api.example.com/main.py", str(target), "0" * 64
    )

    assert result is False


def test_download_file_returns_false_on_non_200_response(mocker):
    mock_get = mocker.patch("app.services.ota.urequests.get")
    mock_get.return_value = make_response(500, text="")

    service = OtaService()
    result = service.download_file("https://api.example.com/main.py", "main.py")

    assert result is False
    mock_get.return_value.close.assert_called_once_with()


def test_download_file_returns_false_when_get_raises(mocker):
    mock_get = mocker.patch("app.services.ota.urequests.get")
    mock_get.side_effect = OSError("network unreachable")

    service = OtaService()
    result = service.download_file("https://api.example.com/main.py", "main.py")

    assert result is False


def test_apply_update_returns_false_when_no_update_available(mocker):
    service = OtaService(manifest_url="https://api.example.com/manifest.json")
    mocker.patch.object(service, "check_for_update", return_value=None)

    result = service.apply_update()

    assert result is False


CONTENT_SHA256 = "fe32608c9ef5b6cf7e3f946480253ff76f24f4ec0678f3d0f07f9844cbff9601"


def test_apply_update_stages_files_then_swaps_and_saves_version(mocker, tmp_path):
    target = tmp_path / "main.py"
    target.write_text("old content")
    manifest = {
        "version": "1.3.0",
        "files": {
            str(target): {
                "url": "https://api.example.com/main.py",
                "sha256": CONTENT_SHA256,
            }
        },
    }
    setting = MagicMock()
    setting.APP_VERSION = "1.2.3"
    service = OtaService(
        manifest_url="https://api.example.com/manifest.json",
        setting=setting,
        state_path=str(tmp_path / "ota_state.json"),
    )
    mocker.patch.object(service, "check_for_update", return_value=manifest)

    def fake_download(url, path, expected_sha256=None):
        with open(path, "w") as f:
            f.write("new content")
        return True

    mock_download = mocker.patch.object(
        service, "download_file", side_effect=fake_download
    )

    result = service.apply_update()

    assert result is True
    mock_download.assert_called_once_with(
        "https://api.example.com/main.py", str(target) + ".ota_new", CONTENT_SHA256
    )
    assert target.read_text() == "new content"
    assert (tmp_path / "main.py.ota_bak").read_text() == "old content"
    assert not (tmp_path / "main.py.ota_new").exists()
    setting.save.assert_called_once_with(app_version="1.3.0")


def test_apply_update_aborts_when_manifest_file_is_plain_url_without_checksum(
    mocker, tmp_path
):
    target = tmp_path / "main.py"
    target.write_text("old content")
    manifest = {
        "version": "1.3.0",
        "files": {str(target): "https://api.example.com/main.py"},
    }
    setting = MagicMock()
    setting.APP_VERSION = "1.2.3"
    service = OtaService(
        manifest_url="https://api.example.com/manifest.json",
        setting=setting,
        state_path=str(tmp_path / "ota_state.json"),
    )
    mocker.patch.object(service, "check_for_update", return_value=manifest)
    mock_download = mocker.patch.object(service, "download_file")

    result = service.apply_update()

    assert result is False
    mock_download.assert_not_called()
    assert target.read_text() == "old content"
    setting.save.assert_not_called()


def test_apply_update_aborts_when_manifest_file_missing_checksum(mocker, tmp_path):
    target = tmp_path / "main.py"
    target.write_text("old content")
    manifest = {
        "version": "1.3.0",
        "files": {str(target): {"url": "https://api.example.com/main.py"}},
    }
    setting = MagicMock()
    setting.APP_VERSION = "1.2.3"
    service = OtaService(
        manifest_url="https://api.example.com/manifest.json",
        setting=setting,
        state_path=str(tmp_path / "ota_state.json"),
    )
    mocker.patch.object(service, "check_for_update", return_value=manifest)
    mock_download = mocker.patch.object(service, "download_file")

    result = service.apply_update()

    assert result is False
    mock_download.assert_not_called()
    assert target.read_text() == "old content"
    setting.save.assert_not_called()


def test_apply_update_backs_up_only_pre_existing_files(mocker, tmp_path):
    target = tmp_path / "new_file.py"
    manifest = {
        "version": "1.3.0",
        "files": {
            str(target): {
                "url": "https://api.example.com/new_file.py",
                "sha256": CONTENT_SHA256,
            }
        },
    }
    setting = MagicMock()
    setting.APP_VERSION = "1.2.3"
    service = OtaService(
        manifest_url="https://api.example.com/manifest.json",
        setting=setting,
        state_path=str(tmp_path / "ota_state.json"),
    )
    mocker.patch.object(service, "check_for_update", return_value=manifest)

    def fake_download(url, path, expected_sha256=None):
        with open(path, "w") as f:
            f.write("new content")
        return True

    mocker.patch.object(service, "download_file", side_effect=fake_download)

    result = service.apply_update()

    assert result is True
    assert target.read_text() == "new content"
    assert not (tmp_path / "new_file.py.ota_bak").exists()


def test_apply_update_aborts_and_cleans_staged_files_when_download_fails(
    mocker, tmp_path
):
    staged_ok = tmp_path / "a.py"
    manifest = {
        "version": "1.3.0",
        "files": {
            str(staged_ok): {
                "url": "https://api.example.com/a.py",
                "sha256": CONTENT_SHA256,
            },
            str(tmp_path / "b.py"): {
                "url": "https://api.example.com/b.py",
                "sha256": CONTENT_SHA256,
            },
        },
    }
    setting = MagicMock()
    setting.APP_VERSION = "1.2.3"
    service = OtaService(
        manifest_url="https://api.example.com/manifest.json",
        setting=setting,
        state_path=str(tmp_path / "ota_state.json"),
    )
    mocker.patch.object(service, "check_for_update", return_value=manifest)

    def fake_download(url, path, expected_sha256=None):
        if path.endswith("a.py.ota_new"):
            with open(path, "w") as f:
                f.write("staged")
            return True
        return False

    mocker.patch.object(service, "download_file", side_effect=fake_download)

    result = service.apply_update()

    assert result is False
    assert not (tmp_path / "a.py.ota_new").exists()
    assert not staged_ok.exists()
    setting.save.assert_not_called()


def test_apply_update_without_setting_still_applies(mocker, tmp_path):
    target = tmp_path / "main.py"
    manifest = {
        "version": "1.3.0",
        "files": {
            str(target): {
                "url": "https://api.example.com/main.py",
                "sha256": CONTENT_SHA256,
            }
        },
    }
    service = OtaService(
        manifest_url="https://api.example.com/manifest.json",
        state_path=str(tmp_path / "ota_state.json"),
    )
    mocker.patch.object(service, "check_for_update", return_value=manifest)

    def fake_download(url, path, expected_sha256=None):
        with open(path, "w") as f:
            f.write("new content")
        return True

    mocker.patch.object(service, "download_file", side_effect=fake_download)

    result = service.apply_update()

    assert result is True
    assert target.read_text() == "new content"


def test_rollback_returns_false_when_no_pending_state(tmp_path):
    service = OtaService(state_path=str(tmp_path / "ota_state.json"))

    assert service.rollback() is False


def test_rollback_prints_and_continues_when_restore_rename_fails(
    mocker, tmp_path, capsys
):
    target = tmp_path / "main.py"
    manifest = {
        "version": "1.3.0",
        "files": {
            str(target): {
                "url": "https://api.example.com/main.py",
                "sha256": CONTENT_SHA256,
            }
        },
    }
    service = OtaService(state_path=str(tmp_path / "ota_state.json"))
    target.write_text("old content")

    def fake_download(url, path, expected_sha256=None):
        with open(path, "w") as f:
            f.write("new content")
        return True

    mocker.patch.object(service, "check_for_update", return_value=manifest)
    mocker.patch.object(service, "download_file", side_effect=fake_download)
    service.apply_update()
    (tmp_path / "main.py.ota_bak").unlink()

    result = service.rollback()

    assert result is True
    out = capsys.readouterr().out
    assert "OTA rollback failed for" in out


def test_write_state_failure_is_printed_not_raised(mocker, tmp_path, capsys):
    target = tmp_path / "main.py"
    manifest = {
        "version": "1.3.0",
        "files": {
            str(target): {
                "url": "https://api.example.com/main.py",
                "sha256": CONTENT_SHA256,
            }
        },
    }
    service = OtaService(state_path=str(tmp_path / "missing_dir" / "ota_state.json"))

    def fake_download(url, path, expected_sha256=None):
        with open(path, "w") as f:
            f.write("new content")
        return True

    mocker.patch.object(service, "check_for_update", return_value=manifest)
    mocker.patch.object(service, "download_file", side_effect=fake_download)

    result = service.apply_update()

    assert result is True
    out = capsys.readouterr().out
    assert "Failed to persist OTA state:" in out


def test_confirm_update_ignores_already_removed_backup(mocker, tmp_path):
    target = tmp_path / "main.py"
    manifest = {
        "version": "1.3.0",
        "files": {
            str(target): {
                "url": "https://api.example.com/main.py",
                "sha256": CONTENT_SHA256,
            }
        },
    }
    service = OtaService(state_path=str(tmp_path / "ota_state.json"))
    target.write_text("old content")

    def fake_download(url, path, expected_sha256=None):
        with open(path, "w") as f:
            f.write("new content")
        return True

    mocker.patch.object(service, "check_for_update", return_value=manifest)
    mocker.patch.object(service, "download_file", side_effect=fake_download)
    service.apply_update()
    (tmp_path / "main.py.ota_bak").unlink()

    service.confirm_update()

    assert not (tmp_path / "ota_state.json").exists()


def test_rollback_restores_backed_up_file_and_removes_new_one(mocker, tmp_path):
    target = tmp_path / "main.py"
    manifest = {
        "version": "1.3.0",
        "files": {
            str(target): {
                "url": "https://api.example.com/main.py",
                "sha256": CONTENT_SHA256,
            }
        },
    }
    setting = MagicMock()
    setting.APP_VERSION = "1.2.3"
    service = OtaService(setting=setting, state_path=str(tmp_path / "ota_state.json"))
    target.write_text("old content")

    def fake_download(url, path, expected_sha256=None):
        with open(path, "w") as f:
            f.write("new content")
        return True

    mocker.patch.object(service, "check_for_update", return_value=manifest)
    mocker.patch.object(service, "download_file", side_effect=fake_download)
    service.apply_update()

    result = service.rollback()

    assert result is True
    assert target.read_text() == "old content"
    assert not (tmp_path / "main.py.ota_bak").exists()
    assert not (tmp_path / "ota_state.json").exists()
    setting.save.assert_called_with(app_version="1.2.3")


def test_rollback_removes_newly_introduced_file_without_backup(mocker, tmp_path):
    target = tmp_path / "new_file.py"
    manifest = {
        "version": "1.3.0",
        "files": {
            str(target): {
                "url": "https://api.example.com/new_file.py",
                "sha256": CONTENT_SHA256,
            }
        },
    }
    service = OtaService(state_path=str(tmp_path / "ota_state.json"))

    def fake_download(url, path, expected_sha256=None):
        with open(path, "w") as f:
            f.write("new content")
        return True

    mocker.patch.object(service, "check_for_update", return_value=manifest)
    mocker.patch.object(service, "download_file", side_effect=fake_download)
    service.apply_update()

    result = service.rollback()

    assert result is True
    assert not target.exists()


def test_confirm_update_returns_none_when_no_pending_state(tmp_path):
    service = OtaService(state_path=str(tmp_path / "ota_state.json"))

    assert service.confirm_update() is None


def test_apply_update_reports_downloading_then_applied_status(mocker, tmp_path):
    target = tmp_path / "main.py"
    manifest = {
        "version": "1.3.0",
        "files": {
            str(target): {
                "url": "https://api.example.com/main.py",
                "sha256": CONTENT_SHA256,
            }
        },
    }
    setting = MagicMock()
    setting.APP_VERSION = "1.2.3"
    on_status = MagicMock()
    service = OtaService(
        manifest_url="https://api.example.com/manifest.json",
        setting=setting,
        state_path=str(tmp_path / "ota_state.json"),
        on_status=on_status,
    )
    mocker.patch.object(service, "check_for_update", return_value=manifest)

    def fake_download(url, path, expected_sha256=None):
        with open(path, "w") as f:
            f.write("new content")
        return True

    mocker.patch.object(service, "download_file", side_effect=fake_download)

    service.apply_update()

    assert on_status.call_args_list == [
        mocker.call({"status": "downloading", "version": "1.3.0"}),
        mocker.call({"status": "applied", "version": "1.3.0"}),
    ]


def test_apply_update_reports_failed_status_on_missing_checksum(mocker, tmp_path):
    target = tmp_path / "main.py"
    manifest = {
        "version": "1.3.0",
        "files": {str(target): "https://api.example.com/main.py"},
    }
    on_status = MagicMock()
    service = OtaService(
        manifest_url="https://api.example.com/manifest.json",
        state_path=str(tmp_path / "ota_state.json"),
        on_status=on_status,
    )
    mocker.patch.object(service, "check_for_update", return_value=manifest)

    service.apply_update()

    assert on_status.call_args_list == [
        mocker.call({"status": "downloading", "version": "1.3.0"}),
        mocker.call(
            {
                "status": "failed",
                "version": "1.3.0",
                "error": "missing checksum for " + str(target),
            }
        ),
    ]


def test_apply_update_reports_failed_status_on_download_failure(mocker, tmp_path):
    target = tmp_path / "main.py"
    manifest = {
        "version": "1.3.0",
        "files": {
            str(target): {
                "url": "https://api.example.com/main.py",
                "sha256": CONTENT_SHA256,
            }
        },
    }
    on_status = MagicMock()
    service = OtaService(
        manifest_url="https://api.example.com/manifest.json",
        state_path=str(tmp_path / "ota_state.json"),
        on_status=on_status,
    )
    mocker.patch.object(service, "check_for_update", return_value=manifest)
    mocker.patch.object(service, "download_file", return_value=False)

    service.apply_update()

    assert on_status.call_args_list == [
        mocker.call({"status": "downloading", "version": "1.3.0"}),
        mocker.call(
            {
                "status": "failed",
                "version": "1.3.0",
                "error": "failed to stage " + str(target),
            }
        ),
    ]


def test_apply_update_without_status_callback_does_not_raise(mocker, tmp_path):
    target = tmp_path / "main.py"
    manifest = {
        "version": "1.3.0",
        "files": {
            str(target): {
                "url": "https://api.example.com/main.py",
                "sha256": CONTENT_SHA256,
            }
        },
    }
    service = OtaService(
        manifest_url="https://api.example.com/manifest.json",
        state_path=str(tmp_path / "ota_state.json"),
    )
    mocker.patch.object(service, "check_for_update", return_value=manifest)

    def fake_download(url, path, expected_sha256=None):
        with open(path, "w") as f:
            f.write("new content")
        return True

    mocker.patch.object(service, "download_file", side_effect=fake_download)

    assert service.apply_update() is True


def test_status_callback_exception_is_printed_not_raised(mocker, tmp_path, capsys):
    target = tmp_path / "main.py"
    manifest = {
        "version": "1.3.0",
        "files": {
            str(target): {
                "url": "https://api.example.com/main.py",
                "sha256": CONTENT_SHA256,
            }
        },
    }
    on_status = MagicMock(side_effect=RuntimeError("mqtt down"))
    service = OtaService(
        manifest_url="https://api.example.com/manifest.json",
        state_path=str(tmp_path / "ota_state.json"),
        on_status=on_status,
    )
    mocker.patch.object(service, "check_for_update", return_value=manifest)

    def fake_download(url, path, expected_sha256=None):
        with open(path, "w") as f:
            f.write("new content")
        return True

    mocker.patch.object(service, "download_file", side_effect=fake_download)

    result = service.apply_update()

    assert result is True
    out = capsys.readouterr().out
    assert "OTA status report failed:" in out


def test_rollback_reports_rolled_back_status(mocker, tmp_path):
    target = tmp_path / "main.py"
    manifest = {
        "version": "1.3.0",
        "files": {
            str(target): {
                "url": "https://api.example.com/main.py",
                "sha256": CONTENT_SHA256,
            }
        },
    }
    setting = MagicMock()
    setting.APP_VERSION = "1.2.3"
    on_status = MagicMock()
    service = OtaService(
        setting=setting,
        state_path=str(tmp_path / "ota_state.json"),
        on_status=on_status,
    )
    target.write_text("old content")

    def fake_download(url, path, expected_sha256=None):
        with open(path, "w") as f:
            f.write("new content")
        return True

    mocker.patch.object(service, "check_for_update", return_value=manifest)
    mocker.patch.object(service, "download_file", side_effect=fake_download)
    service.apply_update()
    on_status.reset_mock()

    service.rollback()

    on_status.assert_called_once_with({"status": "rolled_back", "version": "1.2.3"})


def test_confirm_update_reports_confirmed_status(mocker, tmp_path):
    target = tmp_path / "main.py"
    manifest = {
        "version": "1.3.0",
        "files": {
            str(target): {
                "url": "https://api.example.com/main.py",
                "sha256": CONTENT_SHA256,
            }
        },
    }
    on_status = MagicMock()
    service = OtaService(
        state_path=str(tmp_path / "ota_state.json"),
        on_status=on_status,
    )

    def fake_download(url, path, expected_sha256=None):
        with open(path, "w") as f:
            f.write("new content")
        return True

    mocker.patch.object(service, "check_for_update", return_value=manifest)
    mocker.patch.object(service, "download_file", side_effect=fake_download)
    service.apply_update()
    on_status.reset_mock()

    service.confirm_update()

    on_status.assert_called_once_with({"status": "confirmed", "version": "1.3.0"})


def test_confirm_update_removes_backup_and_clears_state(mocker, tmp_path):
    target = tmp_path / "main.py"
    manifest = {
        "version": "1.3.0",
        "files": {
            str(target): {
                "url": "https://api.example.com/main.py",
                "sha256": CONTENT_SHA256,
            }
        },
    }
    setting = MagicMock()
    setting.APP_VERSION = "1.2.3"
    service = OtaService(setting=setting, state_path=str(tmp_path / "ota_state.json"))
    target.write_text("old content")

    def fake_download(url, path, expected_sha256=None):
        with open(path, "w") as f:
            f.write("new content")
        return True

    mocker.patch.object(service, "check_for_update", return_value=manifest)
    mocker.patch.object(service, "download_file", side_effect=fake_download)
    service.apply_update()

    service.confirm_update()

    assert target.read_text() == "new content"
    assert not (tmp_path / "main.py.ota_bak").exists()
    assert not (tmp_path / "ota_state.json").exists()
