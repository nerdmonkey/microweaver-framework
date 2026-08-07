from unittest.mock import MagicMock

from app.services.registration import RegistrationService


def make_response(status_code=200, json_data=None):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_data or {}
    return response


def test_is_claimed_true_when_setting_has_device_id():
    setting = MagicMock()
    setting.DEVICE_ID = "abc123"

    service = RegistrationService(setting=setting)

    assert service.is_claimed() is True


def test_is_claimed_false_when_setting_has_no_device_id():
    setting = MagicMock()
    setting.DEVICE_ID = ""

    service = RegistrationService(setting=setting)

    assert service.is_claimed() is False


def test_is_claimed_false_without_setting():
    service = RegistrationService()

    assert service.is_claimed() is False


def test_register_skips_without_claim_url():
    service = RegistrationService(claim_url="", claim_code="CODE123")

    result = service.register()

    assert result is None


def test_register_skips_without_claim_code():
    service = RegistrationService(claim_url="https://api.example.com/devices")

    result = service.register()

    assert result is None


def test_register_posts_claim_code_and_saves_identity(mocker):
    mock_post = mocker.patch("app.services.registration.urequests.post")
    mock_post.return_value = make_response(
        200,
        {"device_id": "dev-1", "device_cert": "CERT", "device_key": "KEY"},
    )
    setting = MagicMock()
    service = RegistrationService(
        claim_url="https://api.example.com/devices",
        claim_code="CODE123",
        setting=setting,
    )

    result = service.register()

    mock_post.assert_called_once_with(
        "https://api.example.com/devices", json={"claim_code": "CODE123"}
    )
    setting.save.assert_called_once_with(
        device_id="dev-1",
        device_cert="CERT",
        device_key="KEY",
        claim_code="",
    )
    assert result == {"device_id": "dev-1", "device_cert": "CERT", "device_key": "KEY"}
    mock_post.return_value.close.assert_called_once_with()


def test_register_returns_none_without_setting(mocker):
    mock_post = mocker.patch("app.services.registration.urequests.post")
    mock_post.return_value = make_response(200, {"device_id": "dev-1"})

    service = RegistrationService(
        claim_url="https://api.example.com/devices", claim_code="CODE123"
    )

    result = service.register()

    assert result == {"device_id": "dev-1"}


def test_register_returns_none_on_non_200_response(mocker):
    mock_post = mocker.patch("app.services.registration.urequests.post")
    mock_post.return_value = make_response(401, {})
    setting = MagicMock()

    service = RegistrationService(
        claim_url="https://api.example.com/devices",
        claim_code="CODE123",
        setting=setting,
    )

    result = service.register()

    assert result is None
    setting.save.assert_not_called()
    mock_post.return_value.close.assert_called_once_with()


def test_register_returns_none_when_response_missing_device_id(mocker):
    mock_post = mocker.patch("app.services.registration.urequests.post")
    mock_post.return_value = make_response(200, {})
    setting = MagicMock()

    service = RegistrationService(
        claim_url="https://api.example.com/devices",
        claim_code="CODE123",
        setting=setting,
    )

    result = service.register()

    assert result is None
    setting.save.assert_not_called()


def test_register_returns_none_when_post_raises(mocker):
    mock_post = mocker.patch("app.services.registration.urequests.post")
    mock_post.side_effect = OSError("network unreachable")
    setting = MagicMock()

    service = RegistrationService(
        claim_url="https://api.example.com/devices",
        claim_code="CODE123",
        setting=setting,
    )

    result = service.register()

    assert result is None
    setting.save.assert_not_called()
