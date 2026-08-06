from unittest.mock import MagicMock

import pytest

from app.services.subscribe import SubscribeService


def test_run_reconnects_after_connection_loss(mocker):
    mocker.patch("app.services.subscribe.WiFiService")
    mock_connection_cls = mocker.patch("app.services.subscribe.MqttConnection")
    mock_connection = mock_connection_cls.return_value
    mock_client = MagicMock()
    mock_client.check_msg.side_effect = OSError("dropped")
    mock_connection.connect.side_effect = [mock_client, RuntimeError("stop test")]
    mocker.patch("time.sleep")

    service = SubscribeService()

    with pytest.raises(RuntimeError, match="stop test"):
        service.run()

    mock_client.set_callback.assert_called_once_with(service.on_message)
    mock_client.subscribe.assert_called_once_with(service.topic)
    assert mock_connection.disconnect.call_count == 1


def test_run_reconnects_through_repeated_drops(mocker):
    mocker.patch("app.services.subscribe.WiFiService")
    mock_connection_cls = mocker.patch("app.services.subscribe.MqttConnection")
    mock_connection = mock_connection_cls.return_value
    client_a, client_b = MagicMock(), MagicMock()
    client_a.check_msg.side_effect = OSError("dropped")
    client_b.check_msg.side_effect = ConnectionResetError("dropped again")
    mock_connection.connect.side_effect = [
        client_a,
        client_b,
        RuntimeError("stop test"),
    ]
    mocker.patch("time.sleep")

    service = SubscribeService()

    with pytest.raises(RuntimeError, match="stop test"):
        service.run()

    assert mock_connection.connect.call_count == 3
    assert mock_connection.disconnect.call_count == 2
    client_a.subscribe.assert_called_once_with(service.topic)
    client_b.subscribe.assert_called_once_with(service.topic)


def test_run_feeds_watchdog_each_poll(mocker):
    mocker.patch("app.services.subscribe.WiFiService")
    mock_connection_cls = mocker.patch("app.services.subscribe.MqttConnection")
    mock_connection = mock_connection_cls.return_value
    mock_client = MagicMock()
    mock_client.check_msg.side_effect = [None, None, OSError("dropped")]
    mock_connection.connect.side_effect = [mock_client, RuntimeError("stop test")]
    mocker.patch("time.sleep")

    service = SubscribeService()
    watchdog = MagicMock()
    service.watchdog_service = watchdog

    with pytest.raises(RuntimeError, match="stop test"):
        service.run()

    assert watchdog.feed.call_count == 3


def test_on_message_logs_received_payload(capsys):
    service = SubscribeService()

    service.on_message(b"sensors/temp", b"21.5")

    out = capsys.readouterr().out
    assert "sensors/temp" in out
    assert "21.5" in out


def test_watchdog_disabled_by_default():
    service = SubscribeService()

    assert service.watchdog_service is None


def test_watchdog_started_when_enabled(mocker):
    mocker.patch("app.services.subscribe.setting.WATCHDOG_ENABLED", True)
    mocker.patch("app.services.subscribe.setting.WATCHDOG_TIMEOUT_MS", 4000)
    mock_watchdog_cls = mocker.patch("app.services.subscribe.WatchdogService")
    mock_watchdog = mock_watchdog_cls.return_value

    service = SubscribeService()

    mock_watchdog_cls.assert_called_once_with(4000)
    mock_watchdog.start.assert_called_once_with()
    assert service.watchdog_service is mock_watchdog


def test_bootloop_guard_disabled_by_default():
    service = SubscribeService()

    assert service.bootloop_guard is None


def test_bootloop_guard_created_when_enabled(mocker):
    mocker.patch("app.services.subscribe.setting.BOOT_LOOP_PROTECTION_ENABLED", True)
    mocker.patch("app.services.subscribe.setting.BOOT_LOOP_STATE_PATH", "state.json")
    mocker.patch("app.services.subscribe.setting.BOOT_LOOP_MAX_ATTEMPTS", 3)
    mock_guard_cls = mocker.patch("app.services.subscribe.BootLoopGuard")
    mock_guard = mock_guard_cls.return_value

    service = SubscribeService()

    mock_guard_cls.assert_called_once_with("state.json", 3)
    assert service.bootloop_guard is mock_guard


def test_run_confirms_bootloop_guard_after_connect(mocker):
    mocker.patch("app.services.subscribe.WiFiService")
    mock_connection_cls = mocker.patch("app.services.subscribe.MqttConnection")
    mock_connection = mock_connection_cls.return_value
    mock_client = MagicMock()
    mock_client.check_msg.side_effect = OSError("dropped")
    mock_connection.connect.side_effect = [mock_client, RuntimeError("stop test")]
    mocker.patch("time.sleep")

    service = SubscribeService()
    guard = MagicMock()
    service.bootloop_guard = guard

    with pytest.raises(RuntimeError, match="stop test"):
        service.run()

    guard.confirm.assert_called_once_with()


def test_memory_monitor_disabled_by_default():
    service = SubscribeService()

    assert service.memory_monitor_service is None


def test_memory_monitor_created_when_enabled(mocker):
    mocker.patch("app.services.subscribe.setting.MEMORY_MONITOR_ENABLED", True)
    mocker.patch("app.services.subscribe.setting.MEMORY_MONITOR_THRESHOLD_BYTES", 5000)
    mocker.patch("app.services.subscribe.setting.MEMORY_MONITOR_ACTION", "warn")
    mock_monitor_cls = mocker.patch("app.services.subscribe.MemoryMonitorService")
    mock_monitor = mock_monitor_cls.return_value

    service = SubscribeService()

    mock_monitor_cls.assert_called_once_with(5000, "warn")
    assert service.memory_monitor_service is mock_monitor


def test_run_checks_memory_each_poll(mocker):
    mocker.patch("app.services.subscribe.WiFiService")
    mock_connection_cls = mocker.patch("app.services.subscribe.MqttConnection")
    mock_connection = mock_connection_cls.return_value
    mock_client = MagicMock()
    mock_client.check_msg.side_effect = [None, None, OSError("dropped")]
    mock_connection.connect.side_effect = [mock_client, RuntimeError("stop test")]
    mocker.patch("time.sleep")

    service = SubscribeService()
    memory_monitor = MagicMock()
    service.memory_monitor_service = memory_monitor

    with pytest.raises(RuntimeError, match="stop test"):
        service.run()

    assert memory_monitor.check.call_count == 3
