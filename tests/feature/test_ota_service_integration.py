import hashlib
import json
from unittest.mock import MagicMock

import pytest

import _boot
from app.services.subscribe import SubscribeService, setting


def _manifest_response(manifest):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = manifest
    return response


def _file_response(text):
    response = MagicMock()
    response.status_code = 200
    response.text = text
    return response


def test_ota_topic_message_downloads_verifies_and_applies_real_update(tmp_path, mocker):
    target = tmp_path / "app_main.py"
    target.write_text("print('v1')")
    state_path = tmp_path / "ota_state.json"
    new_content = "print('v2')"
    checksum = hashlib.sha256(new_content.encode()).hexdigest()
    manifest = {
        "version": "2.0.0",
        "files": {
            str(target): {
                "url": "https://cdn.example.com/app_main.py",
                "sha256": checksum,
            }
        },
    }

    mocker.patch("app.services.subscribe.setting.OTA_ENABLED", True)
    mocker.patch(
        "app.services.subscribe.setting.OTA_MANIFEST_URL",
        "https://cdn.example.com/manifest.json",
    )
    mocker.patch("app.services.subscribe.setting.OTA_STATE_PATH", str(state_path))
    mocker.patch("app.services.subscribe.setting.OTA_TOPIC", "ota/update")
    mocker.patch("app.services.subscribe.setting.OTA_STATUS_TOPIC", "ota/status")
    mocker.patch.object(setting, "save")
    mock_get = mocker.patch(
        "app.services.ota.urequests.get",
        side_effect=[_manifest_response(manifest), _file_response(new_content)],
    )

    service = SubscribeService()
    mock_client = MagicMock()
    service.client = mock_client

    service.on_message(b"ota/update", b"check now")

    assert mock_get.call_args_list[0].args == ("https://cdn.example.com/manifest.json",)
    assert mock_get.call_args_list[1].args == ("https://cdn.example.com/app_main.py",)
    assert target.read_text() == new_content
    assert (tmp_path / "app_main.py.ota_bak").read_text() == "print('v1')"
    assert json.loads(state_path.read_text()) == {
        "version": "2.0.0",
        "previous_version": setting.APP_VERSION,
        "files": {str(target): True},
    }
    setting.save.assert_called_once_with(app_version="2.0.0")

    statuses = [
        json.loads(call.args[1].decode())["status"]
        for call in mock_client.publish.call_args_list
    ]
    assert statuses == ["downloading", "applied"]


def test_ota_checksum_mismatch_aborts_real_update_and_reports_failure(tmp_path, mocker):
    target = tmp_path / "app_main.py"
    target.write_text("print('v1')")
    state_path = tmp_path / "ota_state.json"
    manifest = {
        "version": "2.0.0",
        "files": {
            str(target): {
                "url": "https://cdn.example.com/app_main.py",
                "sha256": "0" * 64,
            }
        },
    }

    mocker.patch("app.services.subscribe.setting.OTA_ENABLED", True)
    mocker.patch(
        "app.services.subscribe.setting.OTA_MANIFEST_URL",
        "https://cdn.example.com/manifest.json",
    )
    mocker.patch("app.services.subscribe.setting.OTA_STATE_PATH", str(state_path))
    mocker.patch("app.services.subscribe.setting.OTA_TOPIC", "ota/update")
    mocker.patch("app.services.subscribe.setting.OTA_STATUS_TOPIC", "ota/status")
    mocker.patch.object(setting, "save")
    mocker.patch(
        "app.services.ota.urequests.get",
        side_effect=[
            _manifest_response(manifest),
            _file_response("print('tampered')"),
        ],
    )

    service = SubscribeService()
    mock_client = MagicMock()
    service.client = mock_client

    service.on_message(b"ota/update", b"check now")

    assert target.read_text() == "print('v1')"
    assert not (tmp_path / "app_main.py.ota_new").exists()
    assert not state_path.exists()
    setting.save.assert_not_called()

    statuses = [
        json.loads(call.args[1].decode())["status"]
        for call in mock_client.publish.call_args_list
    ]
    assert statuses == ["downloading", "failed"]


def test_run_confirms_pending_real_ota_update_on_healthy_boot(tmp_path, mocker):
    target = tmp_path / "app_main.py"
    target.write_text("print('v2')")
    backup = tmp_path / "app_main.py.ota_bak"
    backup.write_text("print('v1')")
    state_path = tmp_path / "ota_state.json"
    state_path.write_text(
        json.dumps(
            {
                "version": "2.0.0",
                "previous_version": "1.0.0",
                "files": {str(target): True},
            }
        )
    )

    mocker.patch("app.services.subscribe.setting.MQTT_ENABLED", False)
    mocker.patch("app.services.subscribe.setting.OTA_ENABLED", True)
    mocker.patch("app.services.subscribe.setting.OTA_STATE_PATH", str(state_path))
    mocker.patch("app.services.subscribe.setting.OTA_STATUS_TOPIC", "ota/status")
    mocker.patch("network.WLAN").return_value.isconnected.return_value = True
    mocker.patch("time.sleep", side_effect=KeyboardInterrupt("stop test"))

    service = SubscribeService()
    mock_client = MagicMock()
    service.client = mock_client

    with pytest.raises(KeyboardInterrupt, match="stop test"):
        service.run()

    assert not backup.exists()
    assert not state_path.exists()
    topic, payload = mock_client.publish.call_args.args
    assert topic == "ota/status"
    assert json.loads(payload.decode()) == {
        "status": "confirmed",
        "version": "2.0.0",
        "app_version": setting.APP_VERSION,
    }


def test_boot_rolls_back_real_ota_update_after_boot_loop_detected(tmp_path, mocker):
    target = tmp_path / "app_main.py"
    target.write_text("print('v2-bad')")
    backup = tmp_path / "app_main.py.ota_bak"
    backup.write_text("print('v1-good')")
    state_path = tmp_path / "ota_state.json"
    state_path.write_text(
        json.dumps(
            {
                "version": "2.0.0",
                "previous_version": "1.0.0",
                "files": {str(target): True},
            }
        )
    )

    mocker.patch.object(_boot.setting, "OTA_ENABLED", True)
    mocker.patch.object(_boot.setting, "OTA_MANIFEST_URL", "https://example.com/m.json")
    mocker.patch.object(_boot.setting, "OTA_STATE_PATH", str(state_path))
    mocker.patch.object(_boot.setting, "save")
    mocker.patch("_boot.time")
    mocker.patch("_boot.gc")
    mocker.patch("_boot.ResetService")
    mocker.patch("_boot.CrashLogService")
    guard_cls = mocker.patch("_boot.BootLoopGuard")
    guard_cls.return_value.check.return_value = True
    guard_cls.return_value.attempts = 6
    machine_mock = mocker.patch("_boot.machine")
    mock_main = MagicMock()
    mocker.patch.dict("sys.modules", {"main": mock_main})

    _boot.run_bootstrap()

    assert target.read_text() == "print('v1-good')"
    assert not backup.exists()
    assert not state_path.exists()
    _boot.setting.save.assert_called_once_with(app_version="1.0.0")
    machine_mock.reset.assert_called_once_with()
    mock_main.start_safe_mode.assert_not_called()
