from unittest.mock import MagicMock

import pytest

from app.services.error_handler import ErrorHandlerService
from app.services.runtime import RuntimeService, setting


def test_connect_subscribes_to_each_configured_topic(mocker):
    mocker.patch("app.services.runtime.WiFiService")
    mocker.patch("app.services.runtime.setting.MQTT_TOPIC_SUB", ["topic/a", "topic/b"])
    mock_connection_cls = mocker.patch("app.services.runtime.MqttConnection")
    mock_client = MagicMock()
    mock_connection_cls.return_value.connect.return_value = mock_client

    service = RuntimeService()
    service.connect_to_mqtt()

    assert service.topics == ["topic/a", "topic/b"]
    mock_client.set_callback.assert_called_once_with(service.on_message)
    assert mock_client.subscribe.call_args_list == [
        mocker.call("topic/a"),
        mocker.call("topic/b"),
    ]


def test_topics_override_replaces_configured_mqtt_topic_sub(mocker):
    mocker.patch("app.services.runtime.setting.MQTT_TOPIC_SUB", ["topic/a"])

    service = RuntimeService(topics=[])

    assert service.topics == []


def test_topics_override_is_independent_list_from_input(mocker):
    given_topics = ["custom/topic"]

    service = RuntimeService(topics=given_topics)
    service.topics.append("mutated")

    assert given_topics == ["custom/topic"]


def test_on_message_routes_raw_command_to_single_command_adapter():
    relay = MagicMock()
    service = RuntimeService(subscribe_adapters=[("relay", relay)])

    service.on_message(b"devices/relay", b"on")

    relay.on.assert_called_once_with()


def test_on_message_routes_json_state_to_command_adapter():
    relay = MagicMock()
    service = RuntimeService(subscribe_adapters=[("relay", relay)])

    service.on_message(b"devices/relay", b'{"state": "toggle"}')

    relay.toggle.assert_called_once_with()


def test_on_message_falls_back_to_default_when_topic_does_not_match_multiple_adapters(
    mocker,
):
    relay = MagicMock()
    led = MagicMock()
    service = RuntimeService(subscribe_adapters=[("relay", relay), ("led", led)])
    default_handler = mocker.patch.object(service, "_default_handler")

    service.on_message(b"devices/pump", b"on")

    default_handler.assert_called_once_with(b"devices/pump", b"on")
    relay.on.assert_not_called()
    led.on.assert_not_called()


def test_poll_publish_adapters_publishes_dht22_payload(mocker):
    sensor = MagicMock()
    sensor.read.return_value = (21.5, 55.0)
    service = RuntimeService(publish_adapters=[("dht22", sensor)])
    publish_message = mocker.patch.object(service, "publish_message")

    service._poll_publish_adapters()

    publish_message.assert_called_once_with('{"temperature": 21.5, "humidity": 55.0}')


def test_run_publishes_and_receives_with_one_connection(mocker):
    mocker.patch("app.services.runtime.setting.MQTT_ENABLED", True)
    mock_wifi_cls = mocker.patch("app.services.runtime.WiFiService")
    mock_wifi = mock_wifi_cls.return_value
    mock_connection_cls = mocker.patch("app.services.runtime.MqttConnection")
    mock_connection = mock_connection_cls.return_value
    mock_client = MagicMock()
    mock_client.check_msg.side_effect = [None, OSError("dropped")]
    mock_connection.connect.side_effect = [mock_client, SystemExit("stop test")]
    mocker.patch("time.sleep")
    sensor = MagicMock()
    sensor.read.side_effect = [(21.5, 55.0), None]
    relay = MagicMock()

    service = RuntimeService(
        publish_adapters=[("dht22", sensor)],
        subscribe_adapters=[("relay", relay)],
    )

    with pytest.raises(SystemExit, match="stop test"):
        service.run()

    assert mock_connection.connect.call_count == 2
    assert mock_connection.disconnect.call_count == 2
    assert mock_wifi.ensure_connected.call_count == 2
    mock_client.set_callback.assert_called_once_with(service.on_message)
    mock_client.subscribe.assert_called_once_with(service.topics[0])
    mock_client.publish.assert_called_once_with(
        service.topic,
        b'{"temperature": 21.5, "humidity": 55.0}',
        qos=0,
        retain=False,
    )


def test_run_retries_when_subscribe_fails_during_connect(mocker):
    mocker.patch("app.services.runtime.setting.MQTT_ENABLED", True)
    mock_connection_cls = mocker.patch("app.services.runtime.MqttConnection")
    mock_connection = mock_connection_cls.return_value
    first_client = MagicMock()
    second_client = MagicMock()
    first_client.subscribe.side_effect = RuntimeError("subscribe failed")
    second_client.check_msg.side_effect = OSError("dropped")
    mock_connection.connect.side_effect = [
        first_client,
        second_client,
        SystemExit("stop test"),
    ]
    mock_sleep = mocker.patch("time.sleep")

    service = RuntimeService(subscribe_adapters=[("relay", MagicMock())])
    mocker.patch.object(service.log_service, "log")

    with pytest.raises(SystemExit, match="stop test"):
        service.run()

    assert mock_connection.connect.call_count == 3
    assert mock_connection.disconnect.call_count == 3
    service.log_service.log.assert_any_call(
        "connection_lost",
        level="error",
        error="subscribe failed",
        trace="RuntimeError: subscribe failed",
    )
    mock_sleep.assert_any_call(setting.MQTT_RECONNECT_DELAY_SECONDS)


def test_run_backs_off_with_growing_delay_across_repeated_failures(mocker):
    mocker.patch("app.services.runtime.setting.MQTT_ENABLED", True)
    mocker.patch("app.services.runtime.setting.MQTT_RECONNECT_DELAY_SECONDS", 2)
    mocker.patch("app.services.runtime.setting.MQTT_MAX_RECONNECT_DELAY_SECONDS", 10)
    mock_connection_cls = mocker.patch("app.services.runtime.MqttConnection")
    mock_connection = mock_connection_cls.return_value
    mock_connection.connect.side_effect = [
        RuntimeError("boom 1"),
        RuntimeError("boom 2"),
        RuntimeError("boom 3"),
        SystemExit("stop test"),
    ]
    mock_sleep = mocker.patch("time.sleep")

    service = RuntimeService()

    with pytest.raises(SystemExit, match="stop test"):
        service.run()

    assert mock_sleep.call_args_list == [
        mocker.call(2),
        mocker.call(4),
        mocker.call(8),
    ]


def test_run_resets_backoff_delay_after_successful_reconnect(mocker):
    mocker.patch("app.services.runtime.setting.MQTT_ENABLED", True)
    mocker.patch("app.services.runtime.setting.MQTT_RECONNECT_DELAY_SECONDS", 2)
    mocker.patch("app.services.runtime.setting.MQTT_MAX_RECONNECT_DELAY_SECONDS", 30)
    mock_connection_cls = mocker.patch("app.services.runtime.MqttConnection")
    mock_connection = mock_connection_cls.return_value
    failing_client = MagicMock()
    failing_client.check_msg.side_effect = OSError("dropped")
    mock_connection.connect.side_effect = [
        RuntimeError("boom"),
        failing_client,
        RuntimeError("boom again"),
        SystemExit("stop test"),
    ]
    mock_sleep = mocker.patch("time.sleep")

    service = RuntimeService()

    with pytest.raises(SystemExit, match="stop test"):
        service.run()

    assert mock_sleep.call_args_list == [
        mocker.call(2),
        mocker.call(2),
        mocker.call(4),
    ]


def test_subscribe_reports_friendly_reason_for_suback_failure(mocker):
    from umqtt.simple import MQTTException

    service = RuntimeService(subscribe_adapters=[("relay", MagicMock())])
    service.client = MagicMock()
    service.client.subscribe.side_effect = MQTTException(128)

    with pytest.raises(MQTTException) as excinfo:
        service._subscribe(service.topics[0])

    assert "subscribe_refused" in str(excinfo.value)
    assert "ACL" in str(excinfo.value)


def test_subscribe_reraises_non_suback_failure_unchanged(mocker):
    from umqtt.simple import MQTTException

    service = RuntimeService(subscribe_adapters=[("relay", MagicMock())])
    service.client = MagicMock()
    service.client.subscribe.side_effect = MQTTException(3)

    with pytest.raises(MQTTException) as excinfo:
        service._subscribe(service.topics[0])

    assert excinfo.value.args[0] == 3


# --------------------------------------------------------------------------
# watchdog
# --------------------------------------------------------------------------


def test_watchdog_disabled_by_default():
    service = RuntimeService()

    assert service.watchdog_service is None


def test_watchdog_started_and_registered_when_enabled(mocker):
    mocker.patch("app.services.runtime.setting.WATCHDOG_ENABLED", True)
    mocker.patch("app.services.runtime.setting.WATCHDOG_TIMEOUT_MS", 4000)
    mock_watchdog_cls = mocker.patch("app.services.runtime.WatchdogService")
    mock_watchdog = mock_watchdog_cls.return_value

    service = RuntimeService()

    mock_watchdog_cls.assert_called_once_with(4000)
    mock_watchdog.start.assert_called_once_with()
    assert service.watchdog_service is mock_watchdog


def test_run_feeds_watchdog_each_tick(mocker):
    mocker.patch("app.services.runtime.setting.MQTT_ENABLED", False)
    mock_connection_cls = mocker.patch("app.services.runtime.MqttConnection")
    mock_connection_cls.return_value
    mocker.patch("time.sleep", side_effect=[None, None, SystemExit("stop test")])

    service = RuntimeService()
    watchdog = MagicMock()
    service.watchdog_service = watchdog

    with pytest.raises(SystemExit, match="stop test"):
        service.run()

    assert watchdog.feed.call_count == 3


# --------------------------------------------------------------------------
# WiFi static IP / power save
# --------------------------------------------------------------------------


def test_wifi_service_built_without_static_ip_by_default(mocker):
    mock_wifi_cls = mocker.patch("app.services.runtime.WiFiService")

    RuntimeService()

    assert mock_wifi_cls.call_args.args[-2] is None


def test_wifi_service_built_with_static_ip_when_fully_configured(mocker):
    mocker.patch("app.services.runtime.setting.WIFI_IP", "192.168.1.50")
    mocker.patch("app.services.runtime.setting.WIFI_SUBNET", "255.255.255.0")
    mocker.patch("app.services.runtime.setting.WIFI_GATEWAY", "192.168.1.1")
    mocker.patch("app.services.runtime.setting.WIFI_DNS", "8.8.8.8")
    mock_wifi_cls = mocker.patch("app.services.runtime.WiFiService")

    RuntimeService()

    assert mock_wifi_cls.call_args.args[-2] == (
        "192.168.1.50",
        "255.255.255.0",
        "192.168.1.1",
        "8.8.8.8",
    )


def test_wifi_service_skips_static_ip_when_partially_configured(mocker):
    mocker.patch("app.services.runtime.setting.WIFI_IP", "192.168.1.50")
    mocker.patch("app.services.runtime.setting.WIFI_SUBNET", "255.255.255.0")
    mock_wifi_cls = mocker.patch("app.services.runtime.WiFiService")

    RuntimeService()

    assert mock_wifi_cls.call_args.args[-2] is None


# --------------------------------------------------------------------------
# boot-loop guard
# --------------------------------------------------------------------------


def test_bootloop_guard_disabled_by_default():
    service = RuntimeService()

    assert service.bootloop_guard is None


def test_bootloop_guard_created_when_enabled(mocker):
    mocker.patch("app.services.runtime.setting.BOOT_LOOP_PROTECTION_ENABLED", True)
    mocker.patch("app.services.runtime.setting.BOOT_LOOP_STATE_PATH", "state.json")
    mocker.patch("app.services.runtime.setting.BOOT_LOOP_MAX_ATTEMPTS", 3)
    mock_guard_cls = mocker.patch("app.services.runtime.BootLoopGuard")
    mock_guard = mock_guard_cls.return_value

    service = RuntimeService()

    mock_guard_cls.assert_called_once_with("state.json", 3)
    assert service.bootloop_guard is mock_guard


def test_run_confirms_bootloop_guard_after_connect(mocker):
    mocker.patch("app.services.runtime.setting.MQTT_ENABLED", True)
    mocker.patch("app.services.runtime.WiFiService")
    mock_connection_cls = mocker.patch("app.services.runtime.MqttConnection")
    mock_connection = mock_connection_cls.return_value
    mock_client = MagicMock()
    mock_client.check_msg.side_effect = OSError("dropped")
    mock_connection.connect.side_effect = [mock_client, SystemExit("stop test")]
    mocker.patch("time.sleep")

    service = RuntimeService()
    guard = MagicMock()
    service.bootloop_guard = guard

    with pytest.raises(SystemExit, match="stop test"):
        service.run()

    guard.confirm.assert_called_once_with()


# --------------------------------------------------------------------------
# OTA
# --------------------------------------------------------------------------


def test_ota_service_disabled_by_default():
    service = RuntimeService()

    assert service.ota_service is None


def test_ota_service_created_when_enabled(mocker):
    mocker.patch("app.services.runtime.setting.OTA_ENABLED", True)
    mocker.patch(
        "app.services.runtime.setting.OTA_MANIFEST_URL", "https://example.com/m.json"
    )
    mocker.patch("app.services.runtime.setting.OTA_STATE_PATH", "ota_state.json")
    mock_ota_cls = mocker.patch("app.services.runtime.OtaService")
    mock_ota = mock_ota_cls.return_value

    service = RuntimeService()

    mock_ota_cls.assert_called_once_with(
        "https://example.com/m.json",
        setting=setting,
        state_path="ota_state.json",
        on_status=service._report_ota_status,
    )
    assert service.ota_service is mock_ota


def test_ota_topic_registered_when_ota_enabled(mocker):
    mocker.patch("app.services.runtime.setting.OTA_ENABLED", True)
    mocker.patch("app.services.runtime.setting.OTA_TOPIC", "ota/update")
    mocker.patch("app.services.runtime.OtaService")

    service = RuntimeService()

    assert "ota/update" in service.topics
    assert service.message_handlers["ota/update"] == service._handle_ota_message


def test_ota_topic_not_registered_when_topic_blank(mocker):
    mocker.patch("app.services.runtime.setting.OTA_ENABLED", True)
    mocker.patch("app.services.runtime.setting.OTA_TOPIC", "")
    mocker.patch("app.services.runtime.OtaService")

    service = RuntimeService()

    assert "ota/update" not in service.message_handlers


def test_handle_ota_message_applies_update_via_error_handler():
    service = RuntimeService()
    ota_service = MagicMock()
    service.ota_service = ota_service

    service._handle_ota_message(b"ota/update", b'{"version":"1.2.0"}')

    ota_service.apply_update.assert_called_once_with()


def test_log_level_topic_not_registered_by_default():
    service = RuntimeService()

    assert "device/microweaver/log-level" not in service.topics
    assert "device/microweaver/log-level" not in service.message_handlers


def test_log_level_topic_registered_when_enabled(mocker):
    mocker.patch("app.services.runtime.setting.LOG_LEVEL_OVERRIDE_ENABLED", True)
    mocker.patch(
        "app.services.runtime.setting.LOG_LEVEL_TOPIC", "device/microweaver/log-level"
    )

    service = RuntimeService()

    assert "device/microweaver/log-level" in service.topics
    assert (
        service.message_handlers["device/microweaver/log-level"]
        == service._handle_log_level_message
    )


def test_log_level_topic_not_registered_when_topic_blank(mocker):
    mocker.patch("app.services.runtime.setting.LOG_LEVEL_OVERRIDE_ENABLED", True)
    mocker.patch("app.services.runtime.setting.LOG_LEVEL_TOPIC", "")

    service = RuntimeService()

    assert "" not in service.message_handlers


def test_handle_log_level_message_overrides_level():
    service = RuntimeService()

    service._handle_log_level_message(b"device/microweaver/log-level", b"debug")

    assert service.log_service.level == "debug"


def test_handle_log_level_message_strips_and_lowercases_payload():
    service = RuntimeService()

    service._handle_log_level_message(b"device/microweaver/log-level", b" DEBUG \n")

    assert service.log_service.level == "debug"


def test_handle_log_level_message_logs_override(mocker):
    service = RuntimeService()
    mocker.patch.object(service.log_service, "log")

    service._handle_log_level_message(b"device/microweaver/log-level", b"debug")

    service.log_service.log.assert_called_once_with(
        "log_level_overridden", level="info", new_level="debug"
    )


def test_handle_log_level_message_rejects_unknown_level():
    service = RuntimeService()
    service.log_service.set_level("warning")

    service._handle_log_level_message(b"device/microweaver/log-level", b"bogus")

    assert service.log_service.level == "warning"


def test_handle_log_level_message_logs_rejection(mocker):
    service = RuntimeService()
    mocker.patch.object(service.log_service, "log")

    service._handle_log_level_message(b"device/microweaver/log-level", b"bogus")

    service.log_service.log.assert_called_once_with(
        "log_level_override_rejected", level="warning", requested="bogus"
    )


def test_on_message_routes_log_level_topic_to_handler(mocker):
    mocker.patch("app.services.runtime.setting.LOG_LEVEL_OVERRIDE_ENABLED", True)
    mocker.patch(
        "app.services.runtime.setting.LOG_LEVEL_TOPIC", "device/microweaver/log-level"
    )

    service = RuntimeService()
    service.on_message(b"device/microweaver/log-level", b"debug")

    assert service.log_service.level == "debug"


def test_on_message_routes_ota_topic_to_ota_handler(mocker):
    mocker.patch("app.services.runtime.setting.OTA_ENABLED", True)
    mocker.patch("app.services.runtime.setting.OTA_TOPIC", "ota/update")
    mock_ota_cls = mocker.patch("app.services.runtime.OtaService")
    mock_ota = mock_ota_cls.return_value

    service = RuntimeService()

    service.on_message(b"ota/update", b'{"version":"1.2.0"}')

    mock_ota.apply_update.assert_called_once_with()


def test_run_confirms_ota_update_after_connect(mocker):
    mocker.patch("app.services.runtime.setting.MQTT_ENABLED", True)
    mocker.patch("app.services.runtime.WiFiService")
    mock_connection_cls = mocker.patch("app.services.runtime.MqttConnection")
    mock_connection = mock_connection_cls.return_value
    mock_client = MagicMock()
    mock_client.check_msg.side_effect = OSError("dropped")
    mock_connection.connect.side_effect = [mock_client, SystemExit("stop test")]
    mocker.patch("time.sleep")

    service = RuntimeService()
    ota_service = MagicMock()
    service.ota_service = ota_service

    with pytest.raises(SystemExit, match="stop test"):
        service.run()

    ota_service.confirm_update.assert_called_once_with()


def test_report_ota_status_publishes_json_with_app_version(mocker):
    mocker.patch("app.services.runtime.setting.APP_VERSION", "0.1.0")
    service = RuntimeService()
    service.client = MagicMock()

    service._report_ota_status({"status": "applied", "version": "1.3.0"})

    service.client.publish.assert_called_once_with(
        service.ota_status_topic,
        b'{"status": "applied", "version": "1.3.0", "app_version": "0.1.0"}',
        qos=0,
        retain=False,
    )


# --------------------------------------------------------------------------
# memory monitor
# --------------------------------------------------------------------------


def test_memory_monitor_disabled_by_default():
    service = RuntimeService()

    assert service.memory_monitor_service is None


def test_memory_monitor_created_when_enabled(mocker):
    mocker.patch("app.services.runtime.setting.MEMORY_MONITOR_ENABLED", True)
    mocker.patch("app.services.runtime.setting.MEMORY_MONITOR_THRESHOLD_BYTES", 5000)
    mocker.patch("app.services.runtime.setting.MEMORY_MONITOR_ACTION", "warn")
    mock_monitor_cls = mocker.patch("app.services.runtime.MemoryMonitorService")
    mock_monitor = mock_monitor_cls.return_value

    service = RuntimeService()

    mock_monitor_cls.assert_called_once_with(
        5000, "warn", logger=service.log_service, crash_log=service.crash_log
    )
    assert service.memory_monitor_service is mock_monitor


def test_run_checks_memory_each_tick(mocker):
    mocker.patch("app.services.runtime.setting.MQTT_ENABLED", False)
    mocker.patch("time.sleep", side_effect=[None, None, SystemExit("stop test")])

    service = RuntimeService()
    memory_monitor = MagicMock()
    service.memory_monitor_service = memory_monitor

    with pytest.raises(SystemExit, match="stop test"):
        service.run()

    assert memory_monitor.check.call_count == 3


# --------------------------------------------------------------------------
# health check / service restart / health report
# --------------------------------------------------------------------------


def test_health_check_disabled_by_default():
    service = RuntimeService()

    assert service.health_check_service is None


def test_health_check_created_when_enabled(mocker):
    mocker.patch("app.services.runtime.setting.MQTT_ENABLED", True)
    mocker.patch("app.services.runtime.setting.HEALTH_CHECK_ENABLED", True)
    mocker.patch("app.services.runtime.setting.HEALTH_CHECK_INTERVAL_SECONDS", 15)
    mock_health_cls = mocker.patch("app.services.runtime.HealthCheckService")
    mock_health = mock_health_cls.return_value

    service = RuntimeService()

    mock_health_cls.assert_called_once_with(
        interval_seconds=15,
        logger=service.log_service,
        app_version=setting.APP_VERSION,
        metrics=service.metrics_service,
    )
    assert service.health_check_service is mock_health
    assert mock_health.register.call_args_list[0][0][0] == "wifi"
    assert mock_health.register.call_args_list[1][0][0] == "mqtt"


def test_health_check_skips_mqtt_registration_when_mqtt_disabled(mocker):
    mocker.patch("app.services.runtime.setting.MQTT_ENABLED", False)
    mocker.patch("app.services.runtime.setting.HEALTH_CHECK_ENABLED", True)
    mock_health_cls = mocker.patch("app.services.runtime.HealthCheckService")
    mock_health = mock_health_cls.return_value

    RuntimeService()

    registered = [call.args[0] for call in mock_health.register.call_args_list]
    assert registered == ["wifi"]


def test_service_restart_disabled_by_default():
    service = RuntimeService()

    assert service.service_restart_service is None


def test_service_restart_not_created_without_health_check(mocker):
    mocker.patch("app.services.runtime.setting.SERVICE_RESTART_ENABLED", True)

    service = RuntimeService()

    assert service.service_restart_service is None


def test_service_restart_created_when_enabled(mocker):
    mocker.patch("app.services.runtime.setting.MQTT_ENABLED", True)
    mocker.patch("app.services.runtime.setting.HEALTH_CHECK_ENABLED", True)
    mocker.patch("app.services.runtime.setting.SERVICE_RESTART_ENABLED", True)
    mocker.patch("app.services.runtime.setting.SERVICE_RESTART_MAX_ATTEMPTS", 5)
    mock_restart_cls = mocker.patch("app.services.runtime.ServiceRestartService")
    mock_restart = mock_restart_cls.return_value

    service = RuntimeService()

    mock_restart_cls.assert_called_once_with(max_attempts=5)
    assert service.service_restart_service is mock_restart
    assert mock_restart.register.call_args_list[0][0][0] == "wifi"
    assert mock_restart.register.call_args_list[1][0][0] == "mqtt"


def test_service_restart_skips_mqtt_registration_when_mqtt_disabled(mocker):
    mocker.patch("app.services.runtime.setting.MQTT_ENABLED", False)
    mocker.patch("app.services.runtime.setting.HEALTH_CHECK_ENABLED", True)
    mocker.patch("app.services.runtime.setting.SERVICE_RESTART_ENABLED", True)
    mock_restart_cls = mocker.patch("app.services.runtime.ServiceRestartService")
    mock_restart = mock_restart_cls.return_value

    RuntimeService()

    registered = [call.args[0] for call in mock_restart.register.call_args_list]
    assert registered == ["wifi"]


def test_run_reconciles_service_restart_each_tick(mocker):
    mocker.patch("app.services.runtime.setting.MQTT_ENABLED", True)
    mocker.patch("app.services.runtime.WiFiService")
    mock_connection_cls = mocker.patch("app.services.runtime.MqttConnection")
    mock_connection = mock_connection_cls.return_value
    mock_client = MagicMock()
    mock_client.check_msg.side_effect = OSError("dropped")
    mock_connection.connect.side_effect = [mock_client, SystemExit("stop test")]
    mocker.patch("time.sleep")

    service = RuntimeService()
    health_check = MagicMock()
    health_check.status = {"wifi": {"healthy": False, "error": "timeout"}}
    service.health_check_service = health_check
    service_restart = MagicMock()
    service.service_restart_service = service_restart

    with pytest.raises(SystemExit, match="stop test"):
        service.run()

    service_restart.reconcile.assert_called_once_with(health_check.status)


def test_health_report_disabled_by_default():
    service = RuntimeService()

    assert service.health_report_scheduler is None


def test_health_report_not_created_without_mqtt_enabled(mocker):
    mocker.patch("app.services.runtime.setting.MQTT_ENABLED", False)
    mocker.patch("app.services.runtime.setting.HEALTH_CHECK_ENABLED", True)
    mocker.patch("app.services.runtime.setting.HEALTH_REPORT_ENABLED", True)

    service = RuntimeService()

    assert service.health_report_scheduler is None


def test_health_report_not_created_without_health_check(mocker):
    mocker.patch("app.services.runtime.setting.MQTT_ENABLED", True)
    mocker.patch("app.services.runtime.setting.HEALTH_REPORT_ENABLED", True)

    service = RuntimeService()

    assert service.health_report_scheduler is None


def test_health_report_scheduler_created_when_enabled(mocker):
    mocker.patch("app.services.runtime.setting.MQTT_ENABLED", True)
    mocker.patch("app.services.runtime.setting.HEALTH_CHECK_ENABLED", True)
    mocker.patch("app.services.runtime.setting.HEALTH_REPORT_ENABLED", True)
    mocker.patch("app.services.runtime.setting.HEALTH_REPORT_INTERVAL_SECONDS", 60)

    service = RuntimeService()

    assert service.health_report_scheduler is not None


def test_run_polls_health_report_scheduler_each_tick(mocker):
    mocker.patch("app.services.runtime.setting.MQTT_ENABLED", True)
    mocker.patch("app.services.runtime.setting.HEALTH_CHECK_ENABLED", True)
    mocker.patch("app.services.runtime.setting.HEALTH_REPORT_ENABLED", True)
    mocker.patch("app.services.runtime.setting.HEALTH_REPORT_INTERVAL_SECONDS", 60)
    mocker.patch("app.services.runtime.WiFiService")
    mock_connection_cls = mocker.patch("app.services.runtime.MqttConnection")
    mock_connection = mock_connection_cls.return_value
    mock_client = MagicMock()
    mock_client.check_msg.side_effect = [None, OSError("dropped")]
    mock_connection.connect.side_effect = [mock_client, SystemExit("stop test")]
    mocker.patch("time.sleep")

    service = RuntimeService()
    publish_health_report = mocker.patch.object(service, "_publish_health_report")

    with pytest.raises(SystemExit, match="stop test"):
        service.run()

    publish_health_report.assert_called_once_with()


def test_publish_health_report_publishes_report_json(mocker):
    service = RuntimeService()
    service.client = MagicMock()
    health_check = MagicMock()
    health_check.report.return_value = {"healthy": True}
    service.health_check_service = health_check

    service._publish_health_report()

    service.client.publish.assert_called_once_with(
        service.health_report_topic,
        b'{"healthy": true}',
        qos=0,
        retain=False,
    )


# --------------------------------------------------------------------------
# _publish
# --------------------------------------------------------------------------


def test_publish_records_metrics_on_success():
    service = RuntimeService()
    service.client = MagicMock()

    service._publish("some/topic", "hi")

    assert service.metrics_service.messages_published == 1
    assert service.metrics_service.errors == 0


def test_publish_records_error_on_publish_exception():
    service = RuntimeService()
    service.client = MagicMock()
    service.client.publish.side_effect = OSError("broker unreachable")

    service._publish("some/topic", "hi")

    assert service.metrics_service.messages_published == 0
    assert service.metrics_service.errors == 1


def test_publish_without_client_records_no_metrics():
    service = RuntimeService()
    service.client = None

    service._publish("some/topic", "hi")

    assert service.metrics_service.messages_published == 0
    assert service.metrics_service.errors == 0


# --------------------------------------------------------------------------
# on_message / command handling
# --------------------------------------------------------------------------


def test_default_handler_prints_unmatched_topic(capsys):
    service = RuntimeService()

    service.on_message(b"sensors/unmatched", b"payload")

    out = capsys.readouterr().out
    assert "sensors/unmatched" in out
    assert "payload" in out


def test_handle_command_message_unknown_adapter_falls_back_to_default(mocker):
    relay = MagicMock()
    service = RuntimeService(
        subscribe_adapters=[("relay", relay), ("led", MagicMock())]
    )
    default_handler = mocker.patch.object(service, "_default_handler")

    service._handle_command_message(b"devices/pump", b"on")

    default_handler.assert_called_once_with(b"devices/pump", b"on")
    relay.on.assert_not_called()


def test_handle_command_message_off_command():
    relay = MagicMock()
    service = RuntimeService(subscribe_adapters=[("relay", relay)])

    service._handle_command_message(b"devices/relay", b"off")

    relay.off.assert_called_once_with()


def test_handle_command_message_unsupported_command_prints(capsys):
    relay = MagicMock()
    service = RuntimeService(subscribe_adapters=[("relay", relay)])

    service._handle_command_message(b"devices/relay", b"blink")

    out = capsys.readouterr().out
    assert "Unsupported command" in out
    relay.on.assert_not_called()
    relay.off.assert_not_called()
    relay.toggle.assert_not_called()


def test_resolve_command_adapter_matches_full_topic():
    relay = MagicMock()
    service = RuntimeService(subscribe_adapters=[("devices/relay", relay)])

    resolved = service._resolve_command_adapter("devices/relay")

    assert resolved is relay


def test_decode_command_bool_json_state():
    service = RuntimeService()

    assert service._decode_command(b'{"state": true}') == "on"
    assert service._decode_command(b'{"state": false}') == "off"


# --------------------------------------------------------------------------
# _to_publish_payload
# --------------------------------------------------------------------------


def test_to_publish_payload_dict_reading():
    service = RuntimeService()
    sensor = MagicMock()

    payload = service._to_publish_payload(
        "multi", sensor, {"temperature": 20, "humidity": 40}
    )

    assert payload == '{"temperature": 20, "humidity": 40}'


def test_to_publish_payload_bool_reading():
    service = RuntimeService()
    relay = MagicMock(spec=["read"])

    assert service._to_publish_payload("relay", relay, True) == '{"state": "on"}'
    assert service._to_publish_payload("relay", relay, False) == '{"state": "off"}'


def test_to_publish_payload_numeric_reading():
    service = RuntimeService()
    counter = MagicMock(spec=["read"])

    assert service._to_publish_payload("counter", counter, 42) == '{"value": 42}'


def test_to_publish_payload_unsupported_reading_prints_and_returns_none(capsys):
    service = RuntimeService()
    weird = MagicMock(spec=["read"])

    payload = service._to_publish_payload("weird", weird, object())

    assert payload is None
    assert "Unsupported publish payload" in capsys.readouterr().out


def test_poll_publish_adapters_skips_unsupported_payload(mocker):
    weird = MagicMock(spec=["read", "setup", "deinit"])
    weird.read.return_value = object()
    service = RuntimeService(publish_adapters=[("weird", weird)])
    publish_message = mocker.patch.object(service, "publish_message")

    service._poll_publish_adapters()

    publish_message.assert_not_called()


# --------------------------------------------------------------------------
# _handle_ota_message error handling (mirrors subscribe/publish coverage)
# --------------------------------------------------------------------------


def test_handle_ota_message_logs_and_swallows_apply_update_errors():
    service = RuntimeService()
    ota_service = MagicMock()
    ota_service.apply_update.side_effect = RuntimeError("boom")
    service.ota_service = ota_service
    service.error_handler = ErrorHandlerService(logger=MagicMock())

    service._handle_ota_message(b"ota/update", b"trigger")

    service.error_handler.logger.log.assert_called_once_with(
        "unhandled_exception",
        level="error",
        context="ota_update",
        error="boom",
        trace="RuntimeError: boom",
    )


# --------------------------------------------------------------------------
# stop / misc
# --------------------------------------------------------------------------


def test_stop_tears_down_adapters_in_reverse_order(mocker):
    mocker.patch("app.services.runtime.WiFiService")
    mocker.patch("app.services.runtime.MqttConnection")
    calls = []
    sensor = MagicMock()
    sensor.deinit.side_effect = lambda: calls.append("sensor.deinit")
    relay = MagicMock()
    relay.deinit.side_effect = lambda: calls.append("relay.deinit")

    service = RuntimeService(
        publish_adapters=[("sensor", sensor)], subscribe_adapters=[("relay", relay)]
    )
    service.stop()

    assert calls == ["relay.deinit", "sensor.deinit"]


def test_resolve_command_adapter_single_adapter_fallback():
    relay = MagicMock()
    service = RuntimeService(subscribe_adapters=[("relay", relay)])

    resolved = service._resolve_command_adapter("unrelated/topic")

    assert resolved is relay
