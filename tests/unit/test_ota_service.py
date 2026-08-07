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


def test_apply_update_downloads_files_and_saves_version(mocker, tmp_path):
    target = tmp_path / "main.py"
    manifest = {
        "version": "1.3.0",
        "files": {str(target): "https://api.example.com/main.py"},
    }
    setting = MagicMock()
    setting.APP_VERSION = "1.2.3"
    service = OtaService(
        manifest_url="https://api.example.com/manifest.json", setting=setting
    )
    mocker.patch.object(service, "check_for_update", return_value=manifest)
    mock_download = mocker.patch.object(service, "download_file", return_value=True)

    result = service.apply_update()

    assert result is True
    mock_download.assert_called_once_with(
        "https://api.example.com/main.py", str(target)
    )
    setting.save.assert_called_once_with(app_version="1.3.0")


def test_apply_update_aborts_when_file_download_fails(mocker):
    manifest = {
        "version": "1.3.0",
        "files": {"main.py": "https://api.example.com/main.py"},
    }
    setting = MagicMock()
    setting.APP_VERSION = "1.2.3"
    service = OtaService(
        manifest_url="https://api.example.com/manifest.json", setting=setting
    )
    mocker.patch.object(service, "check_for_update", return_value=manifest)
    mocker.patch.object(service, "download_file", return_value=False)

    result = service.apply_update()

    assert result is False
    setting.save.assert_not_called()


def test_apply_update_without_setting_still_applies(mocker, tmp_path):
    target = tmp_path / "main.py"
    manifest = {
        "version": "1.3.0",
        "files": {str(target): "https://api.example.com/main.py"},
    }
    service = OtaService(manifest_url="https://api.example.com/manifest.json")
    mocker.patch.object(service, "check_for_update", return_value=manifest)
    mocker.patch.object(service, "download_file", return_value=True)

    result = service.apply_update()

    assert result is True
