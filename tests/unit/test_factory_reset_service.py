from unittest.mock import MagicMock

from app.services.factory_reset import FactoryResetService


def make_service(tmp_path, **kwargs):
    kwargs.setdefault("sentinel_path", str(tmp_path / "reprovision.flag"))
    return FactoryResetService(**kwargs)


def test_should_trigger_true_when_sentinel_file_exists(tmp_path):
    sentinel = tmp_path / "reprovision.flag"
    sentinel.write_text("1")
    service = make_service(tmp_path, sentinel_path=str(sentinel))

    assert service.should_trigger() is True


def test_should_trigger_false_when_no_sentinel_and_no_pin(tmp_path):
    service = make_service(tmp_path, pin=-1)

    assert service.should_trigger() is False


def test_should_trigger_false_when_pin_is_none(tmp_path):
    service = make_service(tmp_path, pin=None)

    assert service.should_trigger() is False


def test_button_not_pressed_returns_false(mocker, tmp_path):
    mock_machine = mocker.patch("app.services.factory_reset.machine")
    mock_machine.Pin.return_value.value.return_value = 1
    service = make_service(tmp_path, pin=0)

    assert service.should_trigger() is False


def test_button_released_before_hold_duration_returns_false(mocker, tmp_path):
    mock_machine = mocker.patch("app.services.factory_reset.machine")
    mocker.patch("time.sleep")
    mocker.patch("time.time", side_effect=[0, 0, 1])
    mock_machine.Pin.return_value.value.side_effect = [0, 1]
    service = make_service(tmp_path, pin=0, hold_seconds=3)

    assert service.should_trigger() is False


def test_button_held_for_full_duration_returns_true(mocker, tmp_path):
    mock_machine = mocker.patch("app.services.factory_reset.machine")
    mocker.patch("time.sleep")
    mocker.patch("time.time", side_effect=[0, 0, 1, 2, 3])
    mock_machine.Pin.return_value.value.return_value = 0
    service = make_service(tmp_path, pin=0, hold_seconds=3)

    assert service.should_trigger() is True


def test_clear_credentials_saves_blank_wifi_and_mqtt_fields(tmp_path):
    setting = MagicMock()
    service = make_service(tmp_path, setting=setting)

    service.clear_credentials()

    setting.save.assert_called_once_with(
        wifi_ssid="",
        wifi_password="",
        mqtt_username="",
        mqtt_password="",
        claim_code="",
        device_id="",
        device_cert="",
        device_key="",
    )


def test_clear_credentials_without_setting_does_not_raise(tmp_path):
    service = make_service(tmp_path, setting=None)

    service.clear_credentials()


def test_clear_credentials_removes_sentinel_file(tmp_path):
    sentinel = tmp_path / "reprovision.flag"
    sentinel.write_text("1")
    service = make_service(tmp_path, sentinel_path=str(sentinel))

    service.clear_credentials()

    assert not sentinel.exists()


def test_clear_credentials_is_noop_when_sentinel_missing(tmp_path):
    service = make_service(tmp_path, sentinel_path=str(tmp_path / "missing.flag"))

    service.clear_credentials()
