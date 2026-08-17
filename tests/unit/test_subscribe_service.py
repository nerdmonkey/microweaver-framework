import json
from unittest.mock import MagicMock

import pytest

from app.services.error_handler import ErrorHandlerService
from app.services.metrics import MetricsService
from app.services.mqtt import MqttConnectionRejected
from app.services.subscribe import SubscribeService, setting


def test_run_reconnects_after_connection_loss(mocker):
    mocker.patch("app.services.subscribe.setting.MQTT_ENABLED", True)
    mocker.patch("app.services.subscribe.WiFiService")
    mock_connection_cls = mocker.patch("app.services.subscribe.MqttConnection")
    mock_connection = mock_connection_cls.return_value
    mock_client = MagicMock()
    mock_client.check_msg.side_effect = OSError("dropped")
    mock_connection.connect.side_effect = [mock_client, KeyboardInterrupt("stop test")]
    mocker.patch("time.sleep")

    service = SubscribeService()

    with pytest.raises(KeyboardInterrupt, match="stop test"):
        service.run()

    mock_client.set_callback.assert_called_once_with(service.on_message)
    mock_client.subscribe.assert_called_once_with(service.topics[0])
    assert mock_connection.disconnect.call_count == 2


def test_run_logs_connection_lost_with_trace(mocker):
    mocker.patch("app.services.subscribe.setting.MQTT_ENABLED", True)
    mocker.patch("app.services.subscribe.WiFiService")
    mock_connection_cls = mocker.patch("app.services.subscribe.MqttConnection")
    mock_connection = mock_connection_cls.return_value
    mock_client = MagicMock()
    mock_client.check_msg.side_effect = OSError("dropped")
    mock_connection.connect.side_effect = [mock_client, KeyboardInterrupt("stop test")]
    mocker.patch("time.sleep")

    service = SubscribeService()
    mocker.patch.object(service.log_service, "log")

    with pytest.raises(KeyboardInterrupt, match="stop test"):
        service.run()

    service.log_service.log.assert_called_once_with(
        "connection_lost",
        level="error",
        error="dropped",
        trace="OSError: dropped",
    )


def test_run_records_metrics_error_on_connection_lost(mocker):
    mocker.patch("app.services.subscribe.setting.MQTT_ENABLED", True)
    mocker.patch("app.services.subscribe.WiFiService")
    mock_connection_cls = mocker.patch("app.services.subscribe.MqttConnection")
    mock_connection = mock_connection_cls.return_value
    mock_client = MagicMock()
    mock_client.check_msg.side_effect = OSError("dropped")
    mock_connection.connect.side_effect = [mock_client, KeyboardInterrupt("stop test")]
    mocker.patch("time.sleep")

    service = SubscribeService()

    with pytest.raises(KeyboardInterrupt, match="stop test"):
        service.run()

    assert service.metrics_service.errors == 1


def test_run_backs_off_and_reports_permanent_connection_rejection(mocker):
    # A permanent CONNACK rejection (bad credentials, ACL denial, etc.)
    # shouldn't be retried on the normal ~1s tick cadence - it needs a long
    # cool-down and a distinct, loud log line instead of blending into the
    # generic "connection_lost" noise.
    mocker.patch("app.services.subscribe.setting.MQTT_ENABLED", True)
    mocker.patch("app.services.subscribe.setting.MQTT_REJECTION_RETRY_SECONDS", 300)
    mocker.patch("app.services.subscribe.WiFiService")
    mock_connection_cls = mocker.patch("app.services.subscribe.MqttConnection")
    mock_connection = mock_connection_cls.return_value
    mock_connection.connect.side_effect = [
        MqttConnectionRejected(5, "not_authorized"),
        KeyboardInterrupt("stop test"),
    ]
    mock_sleep = mocker.patch("time.sleep")

    service = SubscribeService()
    mocker.patch.object(service.log_service, "log")

    with pytest.raises(KeyboardInterrupt, match="stop test"):
        service.run()

    service.log_service.log.assert_called_once_with(
        "mqtt_connection_rejected",
        level="error",
        error="MQTT connection rejected: not_authorized (rc=5)",
        rc=5,
        reason="not_authorized",
        trace="MqttConnectionRejected: MQTT connection rejected: not_authorized (rc=5)",
    )
    assert service.metrics_service.errors == 1
    mock_sleep.assert_called_once_with(300)


def test_run_reconnects_through_repeated_drops(mocker):
    mocker.patch("app.services.subscribe.setting.MQTT_ENABLED", True)
    mocker.patch("app.services.subscribe.WiFiService")
    mock_connection_cls = mocker.patch("app.services.subscribe.MqttConnection")
    mock_connection = mock_connection_cls.return_value
    client_a, client_b = MagicMock(), MagicMock()
    client_a.check_msg.side_effect = OSError("dropped")
    client_b.check_msg.side_effect = ConnectionResetError("dropped again")
    mock_connection.connect.side_effect = [
        client_a,
        client_b,
        KeyboardInterrupt("stop test"),
    ]
    mocker.patch("time.sleep")

    service = SubscribeService()

    with pytest.raises(KeyboardInterrupt, match="stop test"):
        service.run()

    assert mock_connection.connect.call_count == 3
    assert mock_connection.disconnect.call_count == 3
    client_a.subscribe.assert_called_once_with(service.topics[0])
    client_b.subscribe.assert_called_once_with(service.topics[0])


def test_run_feeds_watchdog_each_poll(mocker):
    mocker.patch("app.services.subscribe.setting.MQTT_ENABLED", True)
    mocker.patch("app.services.subscribe.WiFiService")
    mock_connection_cls = mocker.patch("app.services.subscribe.MqttConnection")
    mock_connection = mock_connection_cls.return_value
    mock_client = MagicMock()
    mock_client.check_msg.side_effect = [None, None, OSError("dropped")]
    mock_connection.connect.side_effect = [mock_client, KeyboardInterrupt("stop test")]
    mocker.patch("time.sleep")

    service = SubscribeService()
    watchdog = MagicMock()
    service.watchdog_service = watchdog

    with pytest.raises(KeyboardInterrupt, match="stop test"):
        service.run()

    assert watchdog.feed.call_count == 3


def test_run_reconnects_when_broker_denies_subscribe_by_acl_policy(mocker):
    # A broker rejecting a topic via ACL policy manifests as client.subscribe()
    # raising (SUBACK failure code) rather than a network-level drop. That
    # propagates out of connect_to_mqtt() into run()'s generic reconnect
    # handling the same as any other connection loss.
    mocker.patch("app.services.subscribe.setting.MQTT_ENABLED", True)
    mocker.patch("app.services.subscribe.WiFiService")
    mock_connection_cls = mocker.patch("app.services.subscribe.MqttConnection")
    mock_connection = mock_connection_cls.return_value
    denied_client = MagicMock()
    denied_client.subscribe.side_effect = OSError("Not authorized")
    mock_connection.connect.side_effect = [
        denied_client,
        KeyboardInterrupt("stop test"),
    ]
    mocker.patch("time.sleep")

    service = SubscribeService()
    mocker.patch.object(service.log_service, "log")

    with pytest.raises(KeyboardInterrupt, match="stop test"):
        service.run()

    service.log_service.log.assert_called_once_with(
        "connection_lost",
        level="error",
        error="Not authorized",
        trace="OSError: Not authorized",
    )
    assert service.metrics_service.errors == 1
    assert mock_connection.disconnect.call_count == 2


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


def test_on_message_records_metrics_for_every_message():
    service = SubscribeService()
    service.message_handlers["sensors/temp"] = MagicMock()

    service.on_message(b"sensors/temp", b"21.5")
    service.on_message(b"sensors/humidity", b"55")

    assert service.metrics_service.messages_received == 2


def test_on_message_falls_back_to_default_for_unregistered_topic(capsys):
    service = SubscribeService()
    service.message_handlers["sensors/temp"] = MagicMock()

    service.on_message(b"sensors/humidity", b"55")

    out = capsys.readouterr().out
    assert "sensors/humidity" in out
    assert "55" in out


def test_run_checks_wifi_drop_each_poll(mocker):
    mocker.patch("app.services.subscribe.setting.MQTT_ENABLED", True)
    mock_wifi_cls = mocker.patch("app.services.subscribe.WiFiService")
    mock_wifi = mock_wifi_cls.return_value
    mock_connection_cls = mocker.patch("app.services.subscribe.MqttConnection")
    mock_connection = mock_connection_cls.return_value
    mock_client = MagicMock()
    mock_client.check_msg.side_effect = [None, None, OSError("dropped")]
    mock_connection.connect.side_effect = [mock_client, KeyboardInterrupt("stop test")]
    mocker.patch("time.sleep")

    service = SubscribeService()

    with pytest.raises(KeyboardInterrupt, match="stop test"):
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


def test_ssl_params_include_configured_cert_and_key_paths(mocker):
    mocker.patch(
        "app.services.subscribe.setting.MQTT_SSL_CERT_PATH", "/certs/client.crt"
    )
    mocker.patch(
        "app.services.subscribe.setting.MQTT_SSL_KEY_PATH", "/certs/client.key"
    )
    mock_connection_cls = mocker.patch("app.services.subscribe.MqttConnection")

    SubscribeService()

    assert mock_connection_cls.call_args.args[11] == {
        "cert": "/certs/client.crt",
        "key": "/certs/client.key",
    }


def test_ssl_params_omitted_when_no_cert_or_key_path_configured(mocker):
    mocker.patch("app.services.subscribe.setting.MQTT_SSL_CERT_PATH", "")
    mocker.patch("app.services.subscribe.setting.MQTT_SSL_KEY_PATH", "")
    mock_connection_cls = mocker.patch("app.services.subscribe.MqttConnection")

    SubscribeService()

    assert mock_connection_cls.call_args.args[11] is None


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
    mocker.patch("app.services.subscribe.setting.MQTT_ENABLED", True)
    mocker.patch("app.services.subscribe.WiFiService")
    mock_connection_cls = mocker.patch("app.services.subscribe.MqttConnection")
    mock_connection = mock_connection_cls.return_value
    mock_client = MagicMock()
    mock_client.check_msg.side_effect = OSError("dropped")
    mock_connection.connect.side_effect = [mock_client, KeyboardInterrupt("stop test")]
    mocker.patch("time.sleep")

    service = SubscribeService()
    guard = MagicMock()
    service.bootloop_guard = guard

    with pytest.raises(KeyboardInterrupt, match="stop test"):
        service.run()

    guard.confirm.assert_called_once_with()


def test_ota_service_disabled_by_default():
    service = SubscribeService()

    assert service.ota_service is None


def test_ota_service_created_when_enabled(mocker):
    mocker.patch("app.services.subscribe.setting.OTA_ENABLED", True)
    mocker.patch(
        "app.services.subscribe.setting.OTA_MANIFEST_URL", "https://example.com/m.json"
    )
    mocker.patch("app.services.subscribe.setting.OTA_STATE_PATH", "ota_state.json")
    mock_ota_cls = mocker.patch("app.services.subscribe.OtaService")
    mock_ota = mock_ota_cls.return_value

    service = SubscribeService()

    mock_ota_cls.assert_called_once_with(
        "https://example.com/m.json",
        setting=setting,
        state_path="ota_state.json",
        on_status=service._report_ota_status,
    )
    assert service.ota_service is mock_ota


def test_ota_topic_registered_when_ota_enabled(mocker):
    mocker.patch("app.services.subscribe.setting.OTA_ENABLED", True)
    mocker.patch("app.services.subscribe.setting.OTA_TOPIC", "ota/update")
    mocker.patch("app.services.subscribe.OtaService")

    service = SubscribeService()

    assert "ota/update" in service.topics
    assert service.message_handlers["ota/update"] == service._handle_ota_message


def test_ota_topic_not_registered_when_ota_disabled():
    service = SubscribeService()

    assert "ota/update" not in service.topics
    assert "ota/update" not in service.message_handlers


def test_ota_topic_not_registered_when_topic_blank(mocker):
    mocker.patch("app.services.subscribe.setting.OTA_ENABLED", True)
    mocker.patch("app.services.subscribe.setting.OTA_TOPIC", "")
    mocker.patch("app.services.subscribe.OtaService")

    service = SubscribeService()

    assert service.topics == list(setting.MQTT_TOPIC_SUB)
    assert service.message_handlers == {}


def test_handle_ota_message_applies_update_via_error_handler():
    service = SubscribeService()
    ota_service = MagicMock()
    service.ota_service = ota_service

    service._handle_ota_message(b"ota/update", b'{"version":"1.2.0"}')

    ota_service.apply_update.assert_called_once_with()


def test_handle_ota_message_logs_and_swallows_apply_update_errors():
    service = SubscribeService()
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


def test_on_message_routes_ota_topic_to_ota_handler(mocker):
    mocker.patch("app.services.subscribe.setting.OTA_ENABLED", True)
    mocker.patch("app.services.subscribe.setting.OTA_TOPIC", "ota/update")
    mock_ota_cls = mocker.patch("app.services.subscribe.OtaService")
    mock_ota = mock_ota_cls.return_value

    service = SubscribeService()

    service.on_message(b"ota/update", b'{"version":"1.2.0"}')

    mock_ota.apply_update.assert_called_once_with()


def test_run_confirms_ota_update_after_connect(mocker):
    mocker.patch("app.services.subscribe.setting.MQTT_ENABLED", True)
    mocker.patch("app.services.subscribe.WiFiService")
    mock_connection_cls = mocker.patch("app.services.subscribe.MqttConnection")
    mock_connection = mock_connection_cls.return_value
    mock_client = MagicMock()
    mock_client.check_msg.side_effect = OSError("dropped")
    mock_connection.connect.side_effect = [mock_client, KeyboardInterrupt("stop test")]
    mocker.patch("time.sleep")

    service = SubscribeService()
    ota_service = MagicMock()
    service.ota_service = ota_service

    with pytest.raises(KeyboardInterrupt, match="stop test"):
        service.run()

    ota_service.confirm_update.assert_called_once_with()


def test_report_ota_status_publishes_json_with_app_version(mocker):
    mocker.patch("app.services.subscribe.setting.APP_VERSION", "0.1.0")
    service = SubscribeService()
    service.client = MagicMock()

    service._report_ota_status({"status": "applied", "version": "1.3.0"})

    service.client.publish.assert_called_once_with(
        service.ota_status_topic,
        b'{"status": "applied", "version": "1.3.0", "app_version": "0.1.0"}',
        qos=0,
        retain=False,
    )


def test_report_ota_status_without_client_is_noop():
    service = SubscribeService()
    service.client = None

    service._report_ota_status({"status": "applied", "version": "1.3.0"})


def test_metrics_service_is_created():
    service = SubscribeService()

    assert isinstance(service.metrics_service, MetricsService)


def test_publish_records_metrics_on_success():
    service = SubscribeService()
    service.client = MagicMock()

    service._publish("some/topic", "hi")

    assert service.metrics_service.messages_published == 1
    assert service.metrics_service.errors == 0


def test_publish_records_error_on_publish_exception():
    service = SubscribeService()
    service.client = MagicMock()
    service.client.publish.side_effect = OSError("broker unreachable")

    service._publish("some/topic", "hi")

    assert service.metrics_service.messages_published == 0
    assert service.metrics_service.errors == 1


def test_publish_without_client_records_no_metrics():
    service = SubscribeService()
    service.client = None

    service._publish("some/topic", "hi")

    assert service.metrics_service.messages_published == 0
    assert service.metrics_service.errors == 0


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

    mock_monitor_cls.assert_called_once_with(
        5000, "warn", logger=service.log_service, crash_log=service.crash_log
    )
    assert service.memory_monitor_service is mock_monitor


def test_run_checks_memory_each_poll(mocker):
    mocker.patch("app.services.subscribe.setting.MQTT_ENABLED", True)
    mocker.patch("app.services.subscribe.WiFiService")
    mock_connection_cls = mocker.patch("app.services.subscribe.MqttConnection")
    mock_connection = mock_connection_cls.return_value
    mock_client = MagicMock()
    mock_client.check_msg.side_effect = [None, None, OSError("dropped")]
    mock_connection.connect.side_effect = [mock_client, KeyboardInterrupt("stop test")]
    mocker.patch("time.sleep")

    service = SubscribeService()
    memory_monitor = MagicMock()
    service.memory_monitor_service = memory_monitor

    with pytest.raises(KeyboardInterrupt, match="stop test"):
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
    assert service.error_handler.crash_log is service.crash_log
    assert service.error_handler.metrics is service.metrics_service


def test_crash_log_created_from_settings(mocker):
    mocker.patch("app.services.subscribe.setting.CRASH_LOG_PATH", "crash.json")
    mocker.patch("app.services.subscribe.setting.CRASH_LOG_ENABLED", True)
    mocker.patch("app.services.subscribe.setting.CRASH_LOG_MAX_BYTES", 4096)
    crash_log_cls = mocker.patch("app.services.subscribe.CrashLogService")

    service = SubscribeService()

    crash_log_cls.assert_called_once_with("crash.json", True, max_bytes=4096)
    assert service.crash_log is crash_log_cls.return_value


def test_registry_is_wired_with_error_handler():
    service = SubscribeService()

    assert service.registry.error_handler is service.error_handler


def test_no_adapters_by_default():
    service = SubscribeService()

    assert service.adapters == []


def test_adapters_are_registered_and_setup_by_registry(mocker):
    mocker.patch("app.services.subscribe.WiFiService")
    mocker.patch("app.services.subscribe.MqttConnection")
    led = MagicMock()
    relay = MagicMock()

    service = SubscribeService(adapters=[("led", led), ("relay", relay)])

    assert service.adapters == [("led", led), ("relay", relay)]
    led.setup.assert_called_once_with()
    relay.setup.assert_called_once_with()


def test_stop_tears_down_adapters_in_reverse_order(mocker):
    mocker.patch("app.services.subscribe.WiFiService")
    mocker.patch("app.services.subscribe.MqttConnection")
    calls = []
    led = MagicMock()
    led.deinit.side_effect = lambda: calls.append("led.deinit")
    relay = MagicMock()
    relay.deinit.side_effect = lambda: calls.append("relay.deinit")

    service = SubscribeService(adapters=[("led", led), ("relay", relay)])
    service.stop()

    assert calls == ["relay.deinit", "led.deinit"]


def test_run_survives_memory_monitor_exception(mocker):
    mocker.patch("app.services.subscribe.setting.MQTT_ENABLED", True)
    mocker.patch("app.services.subscribe.WiFiService")
    mock_connection_cls = mocker.patch("app.services.subscribe.MqttConnection")
    mock_connection = mock_connection_cls.return_value
    mock_client = MagicMock()
    mock_client.check_msg.side_effect = [None, ConnectionResetError("dropped")]
    mock_connection.connect.side_effect = [mock_client, KeyboardInterrupt("stop test")]
    mocker.patch("time.sleep")

    service = SubscribeService()
    memory_monitor = MagicMock()
    memory_monitor.check.side_effect = OSError("mem read failed")
    service.memory_monitor_service = memory_monitor

    with pytest.raises(KeyboardInterrupt, match="stop test"):
        service.run()

    assert memory_monitor.check.call_count == 2
    assert mock_connection.connect.call_count == 2


def test_run_skips_mqtt_connect_and_check_msg_when_disabled(mocker):
    mocker.patch("app.services.subscribe.setting.MQTT_ENABLED", False)
    mocker.patch("app.services.subscribe.WiFiService")
    mocker.patch("app.services.subscribe.MqttConnection")
    mocker.patch("time.sleep", side_effect=KeyboardInterrupt())

    service = SubscribeService()
    mocker.patch.object(service, "connect_to_mqtt")

    with pytest.raises(KeyboardInterrupt):
        service.run()

    service.connect_to_mqtt.assert_not_called()


def test_health_check_skips_mqtt_registration_when_mqtt_disabled(mocker):
    mocker.patch("app.services.subscribe.setting.MQTT_ENABLED", False)
    mocker.patch("app.services.subscribe.setting.HEALTH_CHECK_ENABLED", True)
    mock_health_cls = mocker.patch("app.services.subscribe.HealthCheckService")
    mock_health = mock_health_cls.return_value

    SubscribeService()

    registered = [call.args[0] for call in mock_health.register.call_args_list]
    assert registered == ["wifi"]


def test_service_restart_skips_mqtt_registration_when_mqtt_disabled(mocker):
    mocker.patch("app.services.subscribe.setting.MQTT_ENABLED", False)
    mocker.patch("app.services.subscribe.setting.HEALTH_CHECK_ENABLED", True)
    mocker.patch("app.services.subscribe.setting.SERVICE_RESTART_ENABLED", True)
    mock_restart_cls = mocker.patch("app.services.subscribe.ServiceRestartService")
    mock_restart = mock_restart_cls.return_value

    SubscribeService()

    registered = [call.args[0] for call in mock_restart.register.call_args_list]
    assert registered == ["wifi"]


def test_health_check_disabled_by_default():
    service = SubscribeService()

    assert service.health_check_service is None


def test_health_check_created_when_enabled(mocker):
    mocker.patch("app.services.subscribe.setting.MQTT_ENABLED", True)
    mocker.patch("app.services.subscribe.setting.HEALTH_CHECK_ENABLED", True)
    mocker.patch("app.services.subscribe.setting.HEALTH_CHECK_INTERVAL_SECONDS", 15)
    mock_health_cls = mocker.patch("app.services.subscribe.HealthCheckService")
    mock_health = mock_health_cls.return_value

    service = SubscribeService()

    mock_health_cls.assert_called_once_with(
        interval_seconds=15,
        logger=service.log_service,
        app_version=setting.APP_VERSION,
        metrics=service.metrics_service,
    )
    assert service.health_check_service is mock_health
    assert mock_health.register.call_args_list[0][0][0] == "wifi"
    assert mock_health.register.call_args_list[1][0][0] == "mqtt"


def test_run_polls_health_check_each_poll(mocker):
    mocker.patch("app.services.subscribe.setting.MQTT_ENABLED", True)
    mocker.patch("app.services.subscribe.WiFiService")
    mock_connection_cls = mocker.patch("app.services.subscribe.MqttConnection")
    mock_connection = mock_connection_cls.return_value
    mock_client = MagicMock()
    mock_client.check_msg.side_effect = [None, None, OSError("dropped")]
    mock_connection.connect.side_effect = [mock_client, KeyboardInterrupt("stop test")]
    mocker.patch("time.sleep")

    service = SubscribeService()
    health_check = MagicMock()
    service.health_check_service = health_check

    with pytest.raises(KeyboardInterrupt, match="stop test"):
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
    mocker.patch("app.services.subscribe.setting.MQTT_ENABLED", True)
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
    mocker.patch("app.services.subscribe.setting.MQTT_ENABLED", True)
    mocker.patch("app.services.subscribe.WiFiService")
    mock_connection_cls = mocker.patch("app.services.subscribe.MqttConnection")
    mock_connection = mock_connection_cls.return_value
    mock_client = MagicMock()
    mock_client.check_msg.side_effect = [None, None, OSError("dropped")]
    mock_connection.connect.side_effect = [mock_client, KeyboardInterrupt("stop test")]
    mocker.patch("time.sleep")

    service = SubscribeService()
    health_check = MagicMock()
    health_check.status = {"wifi": {"healthy": False, "error": "timeout"}}
    service.health_check_service = health_check
    service_restart = MagicMock()
    service.service_restart_service = service_restart

    with pytest.raises(KeyboardInterrupt, match="stop test"):
        service.run()

    assert service_restart.reconcile.call_args_list == [
        mocker.call(health_check.status),
        mocker.call(health_check.status),
        mocker.call(health_check.status),
    ]


def test_health_report_disabled_by_default():
    service = SubscribeService()

    assert service.health_report_scheduler is None


def test_health_report_not_created_without_mqtt_enabled(mocker):
    mocker.patch("app.services.subscribe.setting.MQTT_ENABLED", False)
    mocker.patch("app.services.subscribe.setting.HEALTH_CHECK_ENABLED", True)
    mocker.patch("app.services.subscribe.setting.HEALTH_REPORT_ENABLED", True)

    service = SubscribeService()

    assert service.health_report_scheduler is None


def test_health_report_not_created_without_health_check(mocker):
    mocker.patch("app.services.subscribe.setting.MQTT_ENABLED", True)
    mocker.patch("app.services.subscribe.setting.HEALTH_REPORT_ENABLED", True)

    service = SubscribeService()

    assert service.health_report_scheduler is None


def test_health_report_scheduler_created_when_enabled(mocker):
    mocker.patch("app.services.subscribe.setting.MQTT_ENABLED", True)
    mocker.patch("app.services.subscribe.setting.HEALTH_CHECK_ENABLED", True)
    mocker.patch("app.services.subscribe.setting.HEALTH_REPORT_ENABLED", True)
    mocker.patch("app.services.subscribe.setting.HEALTH_REPORT_INTERVAL_SECONDS", 45)
    mock_scheduler_cls = mocker.patch("app.services.subscribe.PollScheduler")
    mock_scheduler = mock_scheduler_cls.return_value

    service = SubscribeService()

    mock_scheduler_cls.assert_called_once_with(45)
    mock_scheduler.register.assert_called_once_with("health_report")
    assert service.health_report_scheduler is mock_scheduler


def test_run_polls_health_report_scheduler_each_poll(mocker):
    mocker.patch("app.services.subscribe.setting.MQTT_ENABLED", True)
    mocker.patch("app.services.subscribe.WiFiService")
    mock_connection_cls = mocker.patch("app.services.subscribe.MqttConnection")
    mock_connection = mock_connection_cls.return_value
    mock_client = MagicMock()
    mock_client.check_msg.side_effect = [None, None, OSError("dropped")]
    mock_connection.connect.side_effect = [mock_client, KeyboardInterrupt("stop test")]
    mocker.patch("time.sleep")

    service = SubscribeService()
    health_check = MagicMock()
    service.health_check_service = health_check
    health_report_scheduler = MagicMock()
    service.health_report_scheduler = health_report_scheduler

    with pytest.raises(KeyboardInterrupt, match="stop test"):
        service.run()

    assert health_report_scheduler.poll.call_args_list == [
        mocker.call("health_report", service._publish_health_report),
        mocker.call("health_report", service._publish_health_report),
        mocker.call("health_report", service._publish_health_report),
    ]


def test_publish_health_report_publishes_report_json(mocker):
    service = SubscribeService()
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
