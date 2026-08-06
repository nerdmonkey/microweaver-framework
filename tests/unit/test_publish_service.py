from unittest.mock import MagicMock

import pytest

from app.services.publish import PublishService


def test_run_reconnects_after_connection_loss(mocker):
    mocker.patch("app.services.publish.WiFiService")
    mock_connection_cls = mocker.patch("app.services.publish.MqttConnection")
    mock_connection = mock_connection_cls.return_value
    mock_client = MagicMock()
    mock_connection.connect.side_effect = [mock_client, RuntimeError("stop test")]
    mocker.patch("time.sleep", side_effect=ConnectionResetError("dropped"))

    service = PublishService()

    with pytest.raises(RuntimeError, match="stop test"):
        service.run(message="hi")

    assert mock_connection.connect.call_count == 2
    assert mock_connection.disconnect.call_count == 1
    mock_client.publish.assert_called_once_with(service.topic, b"hi")


def test_run_reconnects_through_repeated_drops(mocker):
    mocker.patch("app.services.publish.WiFiService")
    mock_connection_cls = mocker.patch("app.services.publish.MqttConnection")
    mock_connection = mock_connection_cls.return_value
    client_a, client_b = MagicMock(), MagicMock()
    mock_connection.connect.side_effect = [
        client_a,
        client_b,
        RuntimeError("stop test"),
    ]
    mocker.patch(
        "time.sleep",
        side_effect=[ConnectionResetError("dropped"), OSError("dropped again")],
    )

    service = PublishService()

    with pytest.raises(RuntimeError, match="stop test"):
        service.run(message="hi")

    assert mock_connection.connect.call_count == 3
    assert mock_connection.disconnect.call_count == 2
    client_a.publish.assert_called_once_with(service.topic, b"hi")
    client_b.publish.assert_called_once_with(service.topic, b"hi")


def test_run_feeds_watchdog_each_publish(mocker):
    mocker.patch("app.services.publish.WiFiService")
    mock_connection_cls = mocker.patch("app.services.publish.MqttConnection")
    mock_connection = mock_connection_cls.return_value
    mock_client = MagicMock()
    mock_connection.connect.side_effect = [mock_client, RuntimeError("stop test")]
    mocker.patch(
        "time.sleep", side_effect=[None, None, ConnectionResetError("dropped")]
    )

    service = PublishService()
    watchdog = MagicMock()
    service.watchdog_service = watchdog

    with pytest.raises(RuntimeError, match="stop test"):
        service.run(message="hi")

    assert watchdog.feed.call_count == 3


def test_publish_message_survives_publish_exception():
    service = PublishService()
    service.client = MagicMock()
    service.client.publish.side_effect = OSError("broker unreachable")

    service.publish_message("hi")

    service.client.publish.assert_called_once_with(service.topic, b"hi")


def test_publish_message_without_client_is_noop():
    service = PublishService()
    service.client = None

    service.publish_message("hi")


def test_watchdog_disabled_by_default():
    service = PublishService()

    assert service.watchdog_service is None


def test_watchdog_started_when_enabled(mocker):
    mocker.patch("app.services.publish.setting.WATCHDOG_ENABLED", True)
    mocker.patch("app.services.publish.setting.WATCHDOG_TIMEOUT_MS", 4000)
    mock_watchdog_cls = mocker.patch("app.services.publish.WatchdogService")
    mock_watchdog = mock_watchdog_cls.return_value

    service = PublishService()

    mock_watchdog_cls.assert_called_once_with(4000)
    mock_watchdog.start.assert_called_once_with()
    assert service.watchdog_service is mock_watchdog


def test_bootloop_guard_disabled_by_default():
    service = PublishService()

    assert service.bootloop_guard is None


def test_bootloop_guard_created_when_enabled(mocker):
    mocker.patch("app.services.publish.setting.BOOT_LOOP_PROTECTION_ENABLED", True)
    mocker.patch("app.services.publish.setting.BOOT_LOOP_STATE_PATH", "state.json")
    mocker.patch("app.services.publish.setting.BOOT_LOOP_MAX_ATTEMPTS", 3)
    mock_guard_cls = mocker.patch("app.services.publish.BootLoopGuard")
    mock_guard = mock_guard_cls.return_value

    service = PublishService()

    mock_guard_cls.assert_called_once_with("state.json", 3)
    assert service.bootloop_guard is mock_guard


def test_run_confirms_bootloop_guard_after_connect(mocker):
    mocker.patch("app.services.publish.WiFiService")
    mock_connection_cls = mocker.patch("app.services.publish.MqttConnection")
    mock_connection = mock_connection_cls.return_value
    mock_client = MagicMock()
    mock_connection.connect.side_effect = [mock_client, RuntimeError("stop test")]
    mocker.patch("time.sleep", side_effect=ConnectionResetError("dropped"))

    service = PublishService()
    guard = MagicMock()
    service.bootloop_guard = guard

    with pytest.raises(RuntimeError, match="stop test"):
        service.run(message="hi")

    guard.confirm.assert_called_once_with()
