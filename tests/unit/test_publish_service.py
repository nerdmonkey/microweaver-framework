import json
from unittest.mock import MagicMock

import pytest

from app.services.error_handler import ErrorHandlerService
from app.services.publish import PublishService, setting


def test_run_reconnects_after_connection_loss(mocker):
    mocker.patch("app.services.publish.setting.MQTT_ENABLED", True)
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
    mock_client.publish.assert_called_once_with(
        service.topic, b"hi", qos=0, retain=False
    )


def test_run_logs_connection_lost_with_trace(mocker):
    mocker.patch("app.services.publish.setting.MQTT_ENABLED", True)
    mocker.patch("app.services.publish.WiFiService")
    mock_connection_cls = mocker.patch("app.services.publish.MqttConnection")
    mock_connection = mock_connection_cls.return_value
    mock_client = MagicMock()
    mock_connection.connect.side_effect = [mock_client, RuntimeError("stop test")]
    mocker.patch("time.sleep", side_effect=ConnectionResetError("dropped"))

    service = PublishService()
    mocker.patch.object(service.log_service, "log")

    with pytest.raises(RuntimeError, match="stop test"):
        service.run(message="hi")

    service.log_service.log.assert_called_once_with(
        "connection_lost",
        level="error",
        error="dropped",
        trace="ConnectionResetError: dropped",
    )


def test_run_reconnects_through_repeated_drops(mocker):
    mocker.patch("app.services.publish.setting.MQTT_ENABLED", True)
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
    client_a.publish.assert_called_once_with(service.topic, b"hi", qos=0, retain=False)
    client_b.publish.assert_called_once_with(service.topic, b"hi", qos=0, retain=False)


def test_run_feeds_watchdog_each_publish(mocker):
    mocker.patch("app.services.publish.setting.MQTT_ENABLED", True)
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


def test_run_checks_wifi_drop_each_publish(mocker):
    mocker.patch("app.services.publish.setting.MQTT_ENABLED", True)
    mock_wifi_cls = mocker.patch("app.services.publish.WiFiService")
    mock_wifi = mock_wifi_cls.return_value
    mock_connection_cls = mocker.patch("app.services.publish.MqttConnection")
    mock_connection = mock_connection_cls.return_value
    mock_client = MagicMock()
    mock_connection.connect.side_effect = [mock_client, RuntimeError("stop test")]
    mocker.patch(
        "time.sleep", side_effect=[None, None, ConnectionResetError("dropped")]
    )

    service = PublishService()

    with pytest.raises(RuntimeError, match="stop test"):
        service.run(message="hi")

    assert mock_wifi.ensure_connected.call_count == 3


def test_publish_message_survives_publish_exception():
    service = PublishService()
    service.client = MagicMock()
    service.client.publish.side_effect = OSError("broker unreachable")

    service.publish_message("hi")

    service.client.publish.assert_called_once_with(
        service.topic, b"hi", qos=0, retain=False
    )


def test_publish_message_without_client_is_noop():
    service = PublishService()
    service.client = None

    service.publish_message("hi")


def test_publish_message_uses_configured_qos_and_retain(mocker):
    mocker.patch("app.services.publish.setting.MQTT_PUBLISH_QOS", 1)
    mocker.patch("app.services.publish.setting.MQTT_PUBLISH_RETAIN", True)

    service = PublishService()
    service.client = MagicMock()

    service.publish_message("hi")

    service.client.publish.assert_called_once_with(
        service.topic, b"hi", qos=1, retain=True
    )


def test_publish_qos_and_retain_default_to_zero_and_false():
    service = PublishService()

    assert service.publish_qos == 0
    assert service.publish_retain is False


def test_report_ota_status_publishes_json_with_app_version(mocker):
    mocker.patch("app.services.publish.setting.APP_VERSION", "0.1.0")
    service = PublishService()
    service.client = MagicMock()

    service._report_ota_status({"status": "applied", "version": "1.3.0"})

    service.client.publish.assert_called_once_with(
        service.ota_status_topic,
        b'{"status": "applied", "version": "1.3.0", "app_version": "0.1.0"}',
        qos=0,
        retain=False,
    )


def test_report_ota_status_keeps_explicit_app_version(mocker):
    mocker.patch("app.services.publish.setting.APP_VERSION", "0.1.0")
    service = PublishService()
    service.client = MagicMock()

    service._report_ota_status(
        {"status": "applied", "version": "1.3.0", "app_version": "1.3.0"}
    )

    service.client.publish.assert_called_once_with(
        service.ota_status_topic,
        b'{"status": "applied", "version": "1.3.0", "app_version": "1.3.0"}',
        qos=0,
        retain=False,
    )


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


def test_wifi_service_built_without_static_ip_by_default(mocker):
    mock_wifi_cls = mocker.patch("app.services.publish.WiFiService")

    PublishService()

    assert mock_wifi_cls.call_args.args[-2] is None


def test_wifi_service_built_with_static_ip_when_fully_configured(mocker):
    mocker.patch("app.services.publish.setting.WIFI_IP", "192.168.1.50")
    mocker.patch("app.services.publish.setting.WIFI_SUBNET", "255.255.255.0")
    mocker.patch("app.services.publish.setting.WIFI_GATEWAY", "192.168.1.1")
    mocker.patch("app.services.publish.setting.WIFI_DNS", "8.8.8.8")
    mock_wifi_cls = mocker.patch("app.services.publish.WiFiService")

    PublishService()

    assert mock_wifi_cls.call_args.args[-2] == (
        "192.168.1.50",
        "255.255.255.0",
        "192.168.1.1",
        "8.8.8.8",
    )


def test_wifi_service_skips_static_ip_when_partially_configured(mocker):
    mocker.patch("app.services.publish.setting.WIFI_IP", "192.168.1.50")
    mocker.patch("app.services.publish.setting.WIFI_SUBNET", "255.255.255.0")
    mock_wifi_cls = mocker.patch("app.services.publish.WiFiService")

    PublishService()

    assert mock_wifi_cls.call_args.args[-2] is None


def test_wifi_service_built_with_power_save_disabled_by_default(mocker):
    mock_wifi_cls = mocker.patch("app.services.publish.WiFiService")

    PublishService()

    assert mock_wifi_cls.call_args.args[-1] is False


def test_wifi_service_built_with_power_save_disabled_when_configured(mocker):
    mocker.patch("app.services.publish.setting.WIFI_DISABLE_POWER_SAVE", True)
    mock_wifi_cls = mocker.patch("app.services.publish.WiFiService")

    PublishService()

    assert mock_wifi_cls.call_args.args[-1] is True


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
    mocker.patch("app.services.publish.setting.MQTT_ENABLED", True)
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


def test_ota_service_disabled_by_default():
    service = PublishService()

    assert service.ota_service is None


def test_ota_service_created_when_enabled(mocker):
    mocker.patch("app.services.publish.setting.OTA_ENABLED", True)
    mocker.patch(
        "app.services.publish.setting.OTA_MANIFEST_URL", "https://example.com/m.json"
    )
    mocker.patch("app.services.publish.setting.OTA_STATE_PATH", "ota_state.json")
    mock_ota_cls = mocker.patch("app.services.publish.OtaService")
    mock_ota = mock_ota_cls.return_value

    service = PublishService()

    mock_ota_cls.assert_called_once_with(
        "https://example.com/m.json",
        setting=setting,
        state_path="ota_state.json",
        on_status=service._report_ota_status,
    )
    assert service.ota_service is mock_ota


def test_run_confirms_ota_update_after_connect(mocker):
    mocker.patch("app.services.publish.setting.MQTT_ENABLED", True)
    mocker.patch("app.services.publish.WiFiService")
    mock_connection_cls = mocker.patch("app.services.publish.MqttConnection")
    mock_connection = mock_connection_cls.return_value
    mock_client = MagicMock()
    mock_connection.connect.side_effect = [mock_client, RuntimeError("stop test")]
    mocker.patch("time.sleep", side_effect=ConnectionResetError("dropped"))

    service = PublishService()
    ota_service = MagicMock()
    service.ota_service = ota_service

    with pytest.raises(RuntimeError, match="stop test"):
        service.run(message="hi")

    ota_service.confirm_update.assert_called_once_with()


def test_memory_monitor_disabled_by_default():
    service = PublishService()

    assert service.memory_monitor_service is None


def test_memory_monitor_created_when_enabled(mocker):
    mocker.patch("app.services.publish.setting.MEMORY_MONITOR_ENABLED", True)
    mocker.patch("app.services.publish.setting.MEMORY_MONITOR_THRESHOLD_BYTES", 5000)
    mocker.patch("app.services.publish.setting.MEMORY_MONITOR_ACTION", "warn")
    mock_monitor_cls = mocker.patch("app.services.publish.MemoryMonitorService")
    mock_monitor = mock_monitor_cls.return_value

    service = PublishService()

    mock_monitor_cls.assert_called_once_with(
        5000, "warn", logger=service.log_service, crash_log=service.crash_log
    )
    assert service.memory_monitor_service is mock_monitor


def test_run_checks_memory_each_publish(mocker):
    mocker.patch("app.services.publish.setting.MQTT_ENABLED", True)
    mocker.patch("app.services.publish.WiFiService")
    mock_connection_cls = mocker.patch("app.services.publish.MqttConnection")
    mock_connection = mock_connection_cls.return_value
    mock_client = MagicMock()
    mock_connection.connect.side_effect = [mock_client, RuntimeError("stop test")]
    mocker.patch(
        "time.sleep", side_effect=[None, None, ConnectionResetError("dropped")]
    )

    service = PublishService()
    memory_monitor = MagicMock()
    service.memory_monitor_service = memory_monitor

    with pytest.raises(RuntimeError, match="stop test"):
        service.run(message="hi")

    assert memory_monitor.check.call_count == 3


def test_init_wires_wifi_then_mqtt_then_starts_registry(mocker):
    order = []
    wifi_cls = mocker.patch("app.services.publish.WiFiService")
    wifi_cls.side_effect = lambda *a, **k: order.append("wifi_service") or MagicMock()
    connection_cls = mocker.patch("app.services.publish.MqttConnection")
    connection_cls.side_effect = (
        lambda *a, **k: order.append("mqtt_connection") or MagicMock()
    )
    registry_cls = mocker.patch("app.services.publish.ServiceRegistry")
    registry_cls.return_value.start_all.side_effect = lambda: order.append(
        "registry.start_all"
    )

    PublishService()

    assert order == ["wifi_service", "mqtt_connection", "registry.start_all"]


def test_error_handler_is_created():
    service = PublishService()

    assert isinstance(service.error_handler, ErrorHandlerService)
    assert service.error_handler.logger is service.log_service
    assert service.error_handler.crash_log is service.crash_log


def test_crash_log_created_from_settings(mocker):
    mocker.patch("app.services.publish.setting.CRASH_LOG_PATH", "crash.json")
    mocker.patch("app.services.publish.setting.CRASH_LOG_ENABLED", True)
    crash_log_cls = mocker.patch("app.services.publish.CrashLogService")

    service = PublishService()

    crash_log_cls.assert_called_once_with("crash.json", True)
    assert service.crash_log is crash_log_cls.return_value


def test_registry_is_wired_with_error_handler():
    service = PublishService()

    assert service.registry.error_handler is service.error_handler


def test_no_adapters_by_default():
    service = PublishService()

    assert service.adapters == []


def test_adapters_are_registered_and_setup_by_registry(mocker):
    mocker.patch("app.services.publish.WiFiService")
    mocker.patch("app.services.publish.MqttConnection")
    led = MagicMock()
    relay = MagicMock()

    service = PublishService(adapters=[("led", led), ("relay", relay)])

    assert service.adapters == [("led", led), ("relay", relay)]
    led.setup.assert_called_once_with()
    relay.setup.assert_called_once_with()


def test_stop_tears_down_adapters_in_reverse_order(mocker):
    mocker.patch("app.services.publish.WiFiService")
    mocker.patch("app.services.publish.MqttConnection")
    calls = []
    led = MagicMock()
    led.deinit.side_effect = lambda: calls.append("led.deinit")
    relay = MagicMock()
    relay.deinit.side_effect = lambda: calls.append("relay.deinit")

    service = PublishService(adapters=[("led", led), ("relay", relay)])
    service.stop()

    assert calls == ["relay.deinit", "led.deinit"]


def test_run_survives_memory_monitor_exception(mocker):
    mocker.patch("app.services.publish.setting.MQTT_ENABLED", True)
    mocker.patch("app.services.publish.WiFiService")
    mock_connection_cls = mocker.patch("app.services.publish.MqttConnection")
    mock_connection = mock_connection_cls.return_value
    mock_client = MagicMock()
    mock_connection.connect.side_effect = [mock_client, RuntimeError("stop test")]
    mocker.patch("time.sleep", side_effect=[None, ConnectionResetError("dropped")])

    service = PublishService()
    memory_monitor = MagicMock()
    memory_monitor.check.side_effect = OSError("mem read failed")
    service.memory_monitor_service = memory_monitor

    with pytest.raises(RuntimeError, match="stop test"):
        service.run(message="hi")

    assert memory_monitor.check.call_count == 2
    assert mock_connection.connect.call_count == 2
    assert mock_client.publish.call_count == 2


def test_run_skips_mqtt_connect_and_publish_when_disabled(mocker):
    mocker.patch("app.services.publish.setting.MQTT_ENABLED", False)
    mocker.patch("app.services.publish.WiFiService")
    mocker.patch("app.services.publish.MqttConnection")
    mocker.patch("time.sleep", side_effect=KeyboardInterrupt())

    service = PublishService()
    mocker.patch.object(service, "connect_to_mqtt")
    mocker.patch.object(service, "publish_message")

    with pytest.raises(KeyboardInterrupt):
        service.run(message="hi")

    service.connect_to_mqtt.assert_not_called()
    service.publish_message.assert_not_called()


def test_health_check_skips_mqtt_registration_when_mqtt_disabled(mocker):
    mocker.patch("app.services.publish.setting.MQTT_ENABLED", False)
    mocker.patch("app.services.publish.setting.HEALTH_CHECK_ENABLED", True)
    mock_health_cls = mocker.patch("app.services.publish.HealthCheckService")
    mock_health = mock_health_cls.return_value

    PublishService()

    registered = [call.args[0] for call in mock_health.register.call_args_list]
    assert registered == ["wifi"]


def test_service_restart_skips_mqtt_registration_when_mqtt_disabled(mocker):
    mocker.patch("app.services.publish.setting.MQTT_ENABLED", False)
    mocker.patch("app.services.publish.setting.HEALTH_CHECK_ENABLED", True)
    mocker.patch("app.services.publish.setting.SERVICE_RESTART_ENABLED", True)
    mock_restart_cls = mocker.patch("app.services.publish.ServiceRestartService")
    mock_restart = mock_restart_cls.return_value

    PublishService()

    registered = [call.args[0] for call in mock_restart.register.call_args_list]
    assert registered == ["wifi"]


def test_health_check_disabled_by_default():
    service = PublishService()

    assert service.health_check_service is None


def test_health_check_created_when_enabled(mocker):
    mocker.patch("app.services.publish.setting.MQTT_ENABLED", True)
    mocker.patch("app.services.publish.setting.HEALTH_CHECK_ENABLED", True)
    mocker.patch("app.services.publish.setting.HEALTH_CHECK_INTERVAL_SECONDS", 15)
    mock_health_cls = mocker.patch("app.services.publish.HealthCheckService")
    mock_health = mock_health_cls.return_value

    service = PublishService()

    mock_health_cls.assert_called_once_with(
        interval_seconds=15,
        logger=service.log_service,
        app_version=setting.APP_VERSION,
    )
    assert service.health_check_service is mock_health
    assert mock_health.register.call_args_list[0][0][0] == "wifi"
    assert mock_health.register.call_args_list[1][0][0] == "mqtt"


def test_run_polls_health_check_each_publish(mocker):
    mocker.patch("app.services.publish.setting.MQTT_ENABLED", True)
    mocker.patch("app.services.publish.WiFiService")
    mock_connection_cls = mocker.patch("app.services.publish.MqttConnection")
    mock_connection = mock_connection_cls.return_value
    mock_client = MagicMock()
    mock_connection.connect.side_effect = [mock_client, RuntimeError("stop test")]
    mocker.patch(
        "time.sleep", side_effect=[None, None, ConnectionResetError("dropped")]
    )

    service = PublishService()
    health_check = MagicMock()
    service.health_check_service = health_check

    with pytest.raises(RuntimeError, match="stop test"):
        service.run(message="hi")

    assert health_check.poll.call_count == 3


def test_service_restart_disabled_by_default():
    service = PublishService()

    assert service.service_restart_service is None


def test_service_restart_not_created_without_health_check(mocker):
    mocker.patch("app.services.publish.setting.SERVICE_RESTART_ENABLED", True)

    service = PublishService()

    assert service.service_restart_service is None


def test_service_restart_created_when_enabled(mocker):
    mocker.patch("app.services.publish.setting.MQTT_ENABLED", True)
    mocker.patch("app.services.publish.setting.HEALTH_CHECK_ENABLED", True)
    mocker.patch("app.services.publish.setting.SERVICE_RESTART_ENABLED", True)
    mocker.patch("app.services.publish.setting.SERVICE_RESTART_MAX_ATTEMPTS", 5)
    mock_restart_cls = mocker.patch("app.services.publish.ServiceRestartService")
    mock_restart = mock_restart_cls.return_value

    service = PublishService()

    mock_restart_cls.assert_called_once_with(max_attempts=5)
    assert service.service_restart_service is mock_restart
    assert mock_restart.register.call_args_list[0][0][0] == "wifi"
    assert mock_restart.register.call_args_list[1][0][0] == "mqtt"


def test_run_reconciles_service_restart_each_publish(mocker):
    mocker.patch("app.services.publish.setting.MQTT_ENABLED", True)
    mocker.patch("app.services.publish.WiFiService")
    mock_connection_cls = mocker.patch("app.services.publish.MqttConnection")
    mock_connection = mock_connection_cls.return_value
    mock_client = MagicMock()
    mock_connection.connect.side_effect = [mock_client, RuntimeError("stop test")]
    mocker.patch(
        "time.sleep", side_effect=[None, None, ConnectionResetError("dropped")]
    )

    service = PublishService()
    health_check = MagicMock()
    health_check.status = {"wifi": {"healthy": False, "error": "timeout"}}
    service.health_check_service = health_check
    service_restart = MagicMock()
    service.service_restart_service = service_restart

    with pytest.raises(RuntimeError, match="stop test"):
        service.run(message="hi")

    assert service_restart.reconcile.call_args_list == [
        mocker.call(health_check.status),
        mocker.call(health_check.status),
        mocker.call(health_check.status),
    ]


def test_health_report_disabled_by_default():
    service = PublishService()

    assert service.health_report_scheduler is None


def test_health_report_not_created_without_mqtt_enabled(mocker):
    mocker.patch("app.services.publish.setting.MQTT_ENABLED", False)
    mocker.patch("app.services.publish.setting.HEALTH_CHECK_ENABLED", True)
    mocker.patch("app.services.publish.setting.HEALTH_REPORT_ENABLED", True)

    service = PublishService()

    assert service.health_report_scheduler is None


def test_health_report_not_created_without_health_check(mocker):
    mocker.patch("app.services.publish.setting.MQTT_ENABLED", True)
    mocker.patch("app.services.publish.setting.HEALTH_REPORT_ENABLED", True)

    service = PublishService()

    assert service.health_report_scheduler is None


def test_health_report_scheduler_created_when_enabled(mocker):
    mocker.patch("app.services.publish.setting.MQTT_ENABLED", True)
    mocker.patch("app.services.publish.setting.HEALTH_CHECK_ENABLED", True)
    mocker.patch("app.services.publish.setting.HEALTH_REPORT_ENABLED", True)
    mocker.patch("app.services.publish.setting.HEALTH_REPORT_INTERVAL_SECONDS", 45)
    mock_scheduler_cls = mocker.patch("app.services.publish.PollScheduler")
    mock_scheduler = mock_scheduler_cls.return_value

    service = PublishService()

    mock_scheduler_cls.assert_called_once_with(45)
    mock_scheduler.register.assert_called_once_with("health_report")
    assert service.health_report_scheduler is mock_scheduler


def test_run_polls_health_report_scheduler_each_publish(mocker):
    mocker.patch("app.services.publish.setting.MQTT_ENABLED", True)
    mocker.patch("app.services.publish.WiFiService")
    mock_connection_cls = mocker.patch("app.services.publish.MqttConnection")
    mock_connection = mock_connection_cls.return_value
    mock_client = MagicMock()
    mock_connection.connect.side_effect = [mock_client, RuntimeError("stop test")]
    mocker.patch(
        "time.sleep", side_effect=[None, None, ConnectionResetError("dropped")]
    )

    service = PublishService()
    health_check = MagicMock()
    service.health_check_service = health_check
    health_report_scheduler = MagicMock()
    service.health_report_scheduler = health_report_scheduler

    with pytest.raises(RuntimeError, match="stop test"):
        service.run(message="hi")

    assert health_report_scheduler.poll.call_args_list == [
        mocker.call("health_report", service._publish_health_report),
        mocker.call("health_report", service._publish_health_report),
        mocker.call("health_report", service._publish_health_report),
    ]


def test_publish_health_report_publishes_report_json(mocker):
    service = PublishService()
    service.client = MagicMock()
    service.health_report_topic = "device/microweaver/health"
    health_check = MagicMock()
    health_check.report.return_value = {
        "app_version": "0.1.0",
        "healthy": True,
        "checks": {},
    }
    service.health_check_service = health_check

    service._publish_health_report()

    service.client.publish.assert_called_once_with(
        "device/microweaver/health",
        json.dumps(health_check.report.return_value).encode(),
        qos=service.publish_qos,
        retain=service.publish_retain,
    )
