from unittest.mock import MagicMock

import pytest

from app.services.error_handler import ErrorHandlerService
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
    mock_client.subscribe.assert_called_once_with(service.topics[0])
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
    client_a.subscribe.assert_called_once_with(service.topics[0])
    client_b.subscribe.assert_called_once_with(service.topics[0])


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


def test_connect_subscribes_to_each_configured_topic(mocker):
    mocker.patch("app.services.subscribe.WiFiService")
    mocker.patch(
        "app.services.subscribe.setting.MQTT_TOPIC_SUB", ["topic/a", "topic/b"]
    )
    mock_connection_cls = mocker.patch("app.services.subscribe.MqttConnection")
    mock_connection = mock_connection_cls.return_value
    mock_client = MagicMock()
    mock_connection.connect.return_value = mock_client

    service = SubscribeService()
    service.connect_to_mqtt()

    assert service.topics == ["topic/a", "topic/b"]
    assert mock_client.subscribe.call_args_list == [
        mocker.call("topic/a"),
        mocker.call("topic/b"),
    ]


def test_on_message_routes_to_registered_topic_handler():
    service = SubscribeService()
    handler = MagicMock()
    service.message_handlers["sensors/temp"] = handler

    service.on_message(b"sensors/temp", b"21.5")

    handler.assert_called_once_with(b"sensors/temp", b"21.5")


def test_on_message_falls_back_to_default_for_unregistered_topic(capsys):
    service = SubscribeService()
    service.message_handlers["sensors/temp"] = MagicMock()

    service.on_message(b"sensors/humidity", b"55")

    out = capsys.readouterr().out
    assert "sensors/humidity" in out
    assert "55" in out


def test_run_checks_wifi_drop_each_poll(mocker):
    mock_wifi_cls = mocker.patch("app.services.subscribe.WiFiService")
    mock_wifi = mock_wifi_cls.return_value
    mock_connection_cls = mocker.patch("app.services.subscribe.MqttConnection")
    mock_connection = mock_connection_cls.return_value
    mock_client = MagicMock()
    mock_client.check_msg.side_effect = [None, None, OSError("dropped")]
    mock_connection.connect.side_effect = [mock_client, RuntimeError("stop test")]
    mocker.patch("time.sleep")

    service = SubscribeService()

    with pytest.raises(RuntimeError, match="stop test"):
        service.run()

    assert mock_wifi.ensure_connected.call_count == 3


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


def test_wifi_service_built_without_static_ip_by_default(mocker):
    mock_wifi_cls = mocker.patch("app.services.subscribe.WiFiService")

    SubscribeService()

    assert mock_wifi_cls.call_args.args[-2] is None


def test_wifi_service_built_with_static_ip_when_fully_configured(mocker):
    mocker.patch("app.services.subscribe.setting.WIFI_IP", "192.168.1.50")
    mocker.patch("app.services.subscribe.setting.WIFI_SUBNET", "255.255.255.0")
    mocker.patch("app.services.subscribe.setting.WIFI_GATEWAY", "192.168.1.1")
    mocker.patch("app.services.subscribe.setting.WIFI_DNS", "8.8.8.8")
    mock_wifi_cls = mocker.patch("app.services.subscribe.WiFiService")

    SubscribeService()

    assert mock_wifi_cls.call_args.args[-2] == (
        "192.168.1.50",
        "255.255.255.0",
        "192.168.1.1",
        "8.8.8.8",
    )


def test_wifi_service_skips_static_ip_when_partially_configured(mocker):
    mocker.patch("app.services.subscribe.setting.WIFI_IP", "192.168.1.50")
    mocker.patch("app.services.subscribe.setting.WIFI_SUBNET", "255.255.255.0")
    mock_wifi_cls = mocker.patch("app.services.subscribe.WiFiService")

    SubscribeService()

    assert mock_wifi_cls.call_args.args[-2] is None


def test_wifi_service_built_with_power_save_disabled_by_default(mocker):
    mock_wifi_cls = mocker.patch("app.services.subscribe.WiFiService")

    SubscribeService()

    assert mock_wifi_cls.call_args.args[-1] is False


def test_wifi_service_built_with_power_save_disabled_when_configured(mocker):
    mocker.patch("app.services.subscribe.setting.WIFI_DISABLE_POWER_SAVE", True)
    mock_wifi_cls = mocker.patch("app.services.subscribe.WiFiService")

    SubscribeService()

    assert mock_wifi_cls.call_args.args[-1] is True


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

    mock_monitor_cls.assert_called_once_with(5000, "warn", logger=service.log_service)
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


def test_init_wires_wifi_then_mqtt_then_starts_registry(mocker):
    order = []
    wifi_cls = mocker.patch("app.services.subscribe.WiFiService")
    wifi_cls.side_effect = lambda *a, **k: order.append("wifi_service") or MagicMock()
    connection_cls = mocker.patch("app.services.subscribe.MqttConnection")
    connection_cls.side_effect = (
        lambda *a, **k: order.append("mqtt_connection") or MagicMock()
    )
    registry_cls = mocker.patch("app.services.subscribe.ServiceRegistry")
    registry_cls.return_value.start_all.side_effect = lambda: order.append(
        "registry.start_all"
    )

    SubscribeService()

    assert order == ["wifi_service", "mqtt_connection", "registry.start_all"]


def test_error_handler_is_created():
    service = SubscribeService()

    assert isinstance(service.error_handler, ErrorHandlerService)
    assert service.error_handler.logger is service.log_service


def test_registry_is_wired_with_error_handler():
    service = SubscribeService()

    assert service.registry.error_handler is service.error_handler


def test_run_survives_memory_monitor_exception(mocker):
    mocker.patch("app.services.subscribe.WiFiService")
    mock_connection_cls = mocker.patch("app.services.subscribe.MqttConnection")
    mock_connection = mock_connection_cls.return_value
    mock_client = MagicMock()
    mock_client.check_msg.side_effect = [None, ConnectionResetError("dropped")]
    mock_connection.connect.side_effect = [mock_client, RuntimeError("stop test")]
    mocker.patch("time.sleep")

    service = SubscribeService()
    memory_monitor = MagicMock()
    memory_monitor.check.side_effect = OSError("mem read failed")
    service.memory_monitor_service = memory_monitor

    with pytest.raises(RuntimeError, match="stop test"):
        service.run()

    assert memory_monitor.check.call_count == 2
    assert mock_connection.connect.call_count == 2


def test_health_check_disabled_by_default():
    service = SubscribeService()

    assert service.health_check_service is None


def test_health_check_created_when_enabled(mocker):
    mocker.patch("app.services.subscribe.setting.HEALTH_CHECK_ENABLED", True)
    mocker.patch("app.services.subscribe.setting.HEALTH_CHECK_INTERVAL_SECONDS", 15)
    mock_health_cls = mocker.patch("app.services.subscribe.HealthCheckService")
    mock_health = mock_health_cls.return_value

    service = SubscribeService()

    mock_health_cls.assert_called_once_with(
        interval_seconds=15, logger=service.log_service
    )
    assert service.health_check_service is mock_health
    assert mock_health.register.call_args_list[0][0][0] == "wifi"
    assert mock_health.register.call_args_list[1][0][0] == "mqtt"


def test_run_polls_health_check_each_poll(mocker):
    mocker.patch("app.services.subscribe.WiFiService")
    mock_connection_cls = mocker.patch("app.services.subscribe.MqttConnection")
    mock_connection = mock_connection_cls.return_value
    mock_client = MagicMock()
    mock_client.check_msg.side_effect = [None, None, OSError("dropped")]
    mock_connection.connect.side_effect = [mock_client, RuntimeError("stop test")]
    mocker.patch("time.sleep")

    service = SubscribeService()
    health_check = MagicMock()
    service.health_check_service = health_check

    with pytest.raises(RuntimeError, match="stop test"):
        service.run()

    assert health_check.poll.call_count == 3


def test_service_restart_disabled_by_default():
    service = SubscribeService()

    assert service.service_restart_service is None


def test_service_restart_not_created_without_health_check(mocker):
    mocker.patch("app.services.subscribe.setting.SERVICE_RESTART_ENABLED", True)

    service = SubscribeService()

    assert service.service_restart_service is None


def test_service_restart_created_when_enabled(mocker):
    mocker.patch("app.services.subscribe.setting.HEALTH_CHECK_ENABLED", True)
    mocker.patch("app.services.subscribe.setting.SERVICE_RESTART_ENABLED", True)
    mocker.patch("app.services.subscribe.setting.SERVICE_RESTART_MAX_ATTEMPTS", 5)
    mock_restart_cls = mocker.patch("app.services.subscribe.ServiceRestartService")
    mock_restart = mock_restart_cls.return_value

    service = SubscribeService()

    mock_restart_cls.assert_called_once_with(max_attempts=5)
    assert service.service_restart_service is mock_restart
    assert mock_restart.register.call_args_list[0][0][0] == "wifi"
    assert mock_restart.register.call_args_list[1][0][0] == "mqtt"


def test_run_reconciles_service_restart_each_poll(mocker):
    mocker.patch("app.services.subscribe.WiFiService")
    mock_connection_cls = mocker.patch("app.services.subscribe.MqttConnection")
    mock_connection = mock_connection_cls.return_value
    mock_client = MagicMock()
    mock_client.check_msg.side_effect = [None, None, OSError("dropped")]
    mock_connection.connect.side_effect = [mock_client, RuntimeError("stop test")]
    mocker.patch("time.sleep")

    service = SubscribeService()
    health_check = MagicMock()
    health_check.status = {"wifi": {"healthy": False, "error": "timeout"}}
    service.health_check_service = health_check
    service_restart = MagicMock()
    service.service_restart_service = service_restart

    with pytest.raises(RuntimeError, match="stop test"):
        service.run()

    assert service_restart.reconcile.call_args_list == [
        mocker.call(health_check.status),
        mocker.call(health_check.status),
        mocker.call(health_check.status),
    ]
