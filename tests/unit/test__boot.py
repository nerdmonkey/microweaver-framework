from unittest.mock import MagicMock

import pytest

import _boot


@pytest.fixture(autouse=True)
def disable_boot_interrupt_window(mocker):
    mocker.patch.object(_boot.setting, "BOOT_INTERRUPT_WINDOW_SECONDS", 0)
    mocker.patch.object(_boot.setting, "AUTOSTART_ENABLED", True)
    mocker.patch("_boot.time")


def test_run_bootstrap_orders_gc_reset_guard_import_gc_start(mocker):
    mocker.patch.object(_boot.setting, "WIFI_SSID", "TestNet")
    order = []
    gc_mock = mocker.patch("_boot.gc")
    gc_mock.collect.side_effect = lambda: order.append("gc.collect")
    reset_service_cls = mocker.patch("_boot.ResetService")
    reset_service_cls.return_value.read.side_effect = lambda: order.append("reset.read")
    guard_cls = mocker.patch("_boot.BootLoopGuard")

    def check():
        order.append("guard.check")
        return False

    guard_cls.return_value.check.side_effect = check
    mock_main = MagicMock()
    mock_main.start.side_effect = lambda: order.append("main.start")
    mocker.patch.dict("sys.modules", {"main": mock_main})

    _boot.run_bootstrap()

    assert order == [
        "gc.collect",
        "reset.read",
        "guard.check",
        "gc.collect",
        "main.start",
    ]


def test_run_bootstrap_orders_calls_before_safe_mode(mocker):
    order = []
    gc_mock = mocker.patch("_boot.gc")
    gc_mock.collect.side_effect = lambda: order.append("gc.collect")
    reset_service_cls = mocker.patch("_boot.ResetService")
    reset_service_cls.return_value.read.side_effect = lambda: order.append("reset.read")
    guard_cls = mocker.patch("_boot.BootLoopGuard")

    def check():
        order.append("guard.check")
        return True

    guard_cls.return_value.check.side_effect = check
    mock_main = MagicMock()
    mock_main.start_safe_mode.side_effect = lambda: order.append("main.start_safe_mode")
    mocker.patch.dict("sys.modules", {"main": mock_main})

    _boot.run_bootstrap()

    assert order == [
        "gc.collect",
        "reset.read",
        "guard.check",
        "gc.collect",
        "main.start_safe_mode",
    ]
    mock_main.start.assert_not_called()


def test_run_bootstrap_constructs_reset_service_with_logger(mocker):
    mocker.patch.object(_boot.setting, "WIFI_SSID", "TestNet")
    mocker.patch("_boot.gc")
    log_service_cls = mocker.patch("_boot.LogService")
    reset_service_cls = mocker.patch("_boot.ResetService")
    guard_cls = mocker.patch("_boot.BootLoopGuard")
    guard_cls.return_value.check.return_value = False
    mocker.patch.dict("sys.modules", {"main": MagicMock()})

    _boot.run_bootstrap()

    log_service_cls.assert_called_once_with(format=_boot.setting.LOG_FORMAT)
    reset_service_cls.assert_called_once_with(logger=log_service_cls.return_value)


def test_run_bootstrap_constructs_bootloop_guard_with_settings(mocker):
    mocker.patch.object(_boot.setting, "WIFI_SSID", "TestNet")
    mocker.patch("_boot.gc")
    mocker.patch("_boot.ResetService")
    guard_cls = mocker.patch("_boot.BootLoopGuard")
    guard_cls.return_value.check.return_value = False
    mocker.patch.dict("sys.modules", {"main": MagicMock()})

    _boot.run_bootstrap()

    guard_cls.assert_called_once_with(
        _boot.setting.BOOT_LOOP_STATE_PATH,
        _boot.setting.BOOT_LOOP_MAX_ATTEMPTS,
        _boot.setting.BOOT_LOOP_PROTECTION_ENABLED,
    )


def test_run_bootstrap_propagates_reset_service_read_exception(mocker):
    mocker.patch("_boot.gc")
    reset_service_cls = mocker.patch("_boot.ResetService")
    reset_service_cls.return_value.read.side_effect = RuntimeError("nvs corrupt")
    guard_cls = mocker.patch("_boot.BootLoopGuard")
    mock_main = MagicMock()
    mocker.patch.dict("sys.modules", {"main": mock_main})

    with pytest.raises(RuntimeError, match="nvs corrupt"):
        _boot.run_bootstrap()

    guard_cls.return_value.check.assert_not_called()
    mock_main.start.assert_not_called()
    mock_main.start_safe_mode.assert_not_called()


def test_run_bootstrap_imports_main_and_starts(mocker):
    mocker.patch.object(_boot.setting, "WIFI_SSID", "TestNet")
    gc_mock = mocker.patch("_boot.gc")
    reset_service_cls = mocker.patch("_boot.ResetService")
    guard_cls = mocker.patch("_boot.BootLoopGuard")
    guard_cls.return_value.check.return_value = False
    mock_main = MagicMock()
    mocker.patch.dict("sys.modules", {"main": mock_main})

    _boot.run_bootstrap()

    assert gc_mock.collect.call_count == 2
    reset_service_cls.return_value.read.assert_called_once_with()
    guard_cls.return_value.check.assert_called_once_with()
    mock_main.start.assert_called_once_with()


def test_run_bootstrap_enters_safe_mode_when_boot_loop_detected(mocker):
    gc_mock = mocker.patch("_boot.gc")
    mocker.patch("_boot.ResetService")
    guard_cls = mocker.patch("_boot.BootLoopGuard")
    guard_cls.return_value.check.return_value = True
    mock_main = MagicMock()
    mocker.patch.dict("sys.modules", {"main": mock_main})

    _boot.run_bootstrap()

    assert gc_mock.collect.call_count == 2
    mock_main.start.assert_not_called()
    mock_main.start_safe_mode.assert_called_once_with()


def test_run_bootstrap_enters_provisioning_when_wifi_ssid_unconfigured(mocker):
    mocker.patch.object(_boot.setting, "WIFI_SSID", "")
    gc_mock = mocker.patch("_boot.gc")
    mocker.patch("_boot.ResetService")
    guard_cls = mocker.patch("_boot.BootLoopGuard")
    guard_cls.return_value.check.return_value = False
    mock_main = MagicMock()
    mocker.patch.dict("sys.modules", {"main": mock_main})

    _boot.run_bootstrap()

    assert gc_mock.collect.call_count == 2
    mock_main.start.assert_not_called()
    mock_main.start_safe_mode.assert_not_called()
    mock_main.start_provisioning.assert_called_once_with()


def test_run_bootstrap_stops_when_autostart_disabled(mocker):
    mocker.patch.object(_boot.setting, "WIFI_SSID", "TestNet")
    mocker.patch.object(_boot.setting, "AUTOSTART_ENABLED", False)
    gc_mock = mocker.patch("_boot.gc")
    mocker.patch("_boot.ResetService")
    guard_cls = mocker.patch("_boot.BootLoopGuard")
    guard_cls.return_value.check.return_value = False
    mock_main = MagicMock()
    mocker.patch.dict("sys.modules", {"main": mock_main})

    _boot.run_bootstrap()

    assert gc_mock.collect.call_count == 2
    mock_main.start.assert_not_called()
    mock_main.start_safe_mode.assert_not_called()
    mock_main.start_provisioning.assert_not_called()


def test_run_bootstrap_skips_factory_reset_when_disabled(mocker):
    mocker.patch.object(_boot.setting, "WIFI_SSID", "TestNet")
    mocker.patch.object(_boot.setting, "FACTORY_RESET_ENABLED", False)
    mocker.patch("_boot.gc")
    mocker.patch("_boot.ResetService")
    guard_cls = mocker.patch("_boot.BootLoopGuard")
    guard_cls.return_value.check.return_value = False
    factory_reset_cls = mocker.patch("_boot.FactoryResetService")
    mocker.patch.dict("sys.modules", {"main": MagicMock()})

    _boot.run_bootstrap()

    factory_reset_cls.assert_not_called()


def test_run_bootstrap_constructs_factory_reset_service_with_settings(mocker):
    mocker.patch.object(_boot.setting, "WIFI_SSID", "TestNet")
    mocker.patch.object(_boot.setting, "FACTORY_RESET_ENABLED", True)
    mocker.patch("_boot.gc")
    mocker.patch("_boot.ResetService")
    guard_cls = mocker.patch("_boot.BootLoopGuard")
    guard_cls.return_value.check.return_value = False
    factory_reset_cls = mocker.patch("_boot.FactoryResetService")
    factory_reset_cls.return_value.should_trigger.return_value = False
    mocker.patch.dict("sys.modules", {"main": MagicMock()})

    _boot.run_bootstrap()

    factory_reset_cls.assert_called_once_with(
        pin=_boot.setting.FACTORY_RESET_PIN,
        hold_seconds=_boot.setting.FACTORY_RESET_HOLD_SECONDS,
        sentinel_path=_boot.setting.FACTORY_RESET_SENTINEL_PATH,
        setting=_boot.setting,
    )


def test_run_bootstrap_clears_credentials_when_factory_reset_triggered(mocker):
    mocker.patch.object(_boot.setting, "WIFI_SSID", "TestNet")
    mocker.patch.object(_boot.setting, "FACTORY_RESET_ENABLED", True)
    mocker.patch("_boot.gc")
    mocker.patch("_boot.ResetService")
    guard_cls = mocker.patch("_boot.BootLoopGuard")
    guard_cls.return_value.check.return_value = False
    factory_reset_cls = mocker.patch("_boot.FactoryResetService")
    factory_reset_cls.return_value.should_trigger.return_value = True
    mocker.patch.dict("sys.modules", {"main": MagicMock()})

    _boot.run_bootstrap()

    factory_reset_cls.return_value.clear_credentials.assert_called_once_with()


def test_run_bootstrap_does_not_clear_credentials_when_not_triggered(mocker):
    mocker.patch.object(_boot.setting, "WIFI_SSID", "TestNet")
    mocker.patch.object(_boot.setting, "FACTORY_RESET_ENABLED", True)
    mocker.patch("_boot.gc")
    mocker.patch("_boot.ResetService")
    guard_cls = mocker.patch("_boot.BootLoopGuard")
    guard_cls.return_value.check.return_value = False
    factory_reset_cls = mocker.patch("_boot.FactoryResetService")
    factory_reset_cls.return_value.should_trigger.return_value = False
    mocker.patch.dict("sys.modules", {"main": MagicMock()})

    _boot.run_bootstrap()

    factory_reset_cls.return_value.clear_credentials.assert_not_called()


def test_run_bootstrap_prefers_safe_mode_over_provisioning_when_both_apply(mocker):
    mocker.patch.object(_boot.setting, "WIFI_SSID", "")
    mocker.patch("_boot.gc")
    mocker.patch("_boot.ResetService")
    guard_cls = mocker.patch("_boot.BootLoopGuard")
    guard_cls.return_value.check.return_value = True
    mock_main = MagicMock()
    mocker.patch.dict("sys.modules", {"main": mock_main})

    _boot.run_bootstrap()

    mock_main.start_safe_mode.assert_called_once_with()
    mock_main.start_provisioning.assert_not_called()
    mock_main.start.assert_not_called()


def test_run_bootstrap_claims_device_when_enabled_and_unclaimed(mocker):
    mocker.patch.object(_boot.setting, "WIFI_SSID", "TestNet")
    mocker.patch.object(_boot.setting, "CLAIM_ENABLED", True)
    mocker.patch.object(_boot.setting, "DEVICE_ID", "")
    mocker.patch.object(_boot.setting, "CLAIM_CODE", "CODE123")
    mocker.patch("_boot.gc")
    mocker.patch("_boot.ResetService")
    guard_cls = mocker.patch("_boot.BootLoopGuard")
    guard_cls.return_value.check.return_value = False
    mock_main = MagicMock()
    mocker.patch.dict("sys.modules", {"main": mock_main})

    _boot.run_bootstrap()

    mock_main.start_claim.assert_called_once_with()
    mock_main.start.assert_called_once_with()


def test_run_bootstrap_skips_claim_when_disabled(mocker):
    mocker.patch.object(_boot.setting, "WIFI_SSID", "TestNet")
    mocker.patch.object(_boot.setting, "CLAIM_ENABLED", False)
    mocker.patch.object(_boot.setting, "DEVICE_ID", "")
    mocker.patch.object(_boot.setting, "CLAIM_CODE", "CODE123")
    mocker.patch("_boot.gc")
    mocker.patch("_boot.ResetService")
    guard_cls = mocker.patch("_boot.BootLoopGuard")
    guard_cls.return_value.check.return_value = False
    mock_main = MagicMock()
    mocker.patch.dict("sys.modules", {"main": mock_main})

    _boot.run_bootstrap()

    mock_main.start_claim.assert_not_called()
    mock_main.start.assert_called_once_with()


def test_run_bootstrap_skips_claim_when_already_claimed(mocker):
    mocker.patch.object(_boot.setting, "WIFI_SSID", "TestNet")
    mocker.patch.object(_boot.setting, "CLAIM_ENABLED", True)
    mocker.patch.object(_boot.setting, "DEVICE_ID", "dev-1")
    mocker.patch.object(_boot.setting, "CLAIM_CODE", "CODE123")
    mocker.patch("_boot.gc")
    mocker.patch("_boot.ResetService")
    guard_cls = mocker.patch("_boot.BootLoopGuard")
    guard_cls.return_value.check.return_value = False
    mock_main = MagicMock()
    mocker.patch.dict("sys.modules", {"main": mock_main})

    _boot.run_bootstrap()

    mock_main.start_claim.assert_not_called()
    mock_main.start.assert_called_once_with()


def test_run_bootstrap_skips_claim_when_no_claim_code(mocker):
    mocker.patch.object(_boot.setting, "WIFI_SSID", "TestNet")
    mocker.patch.object(_boot.setting, "CLAIM_ENABLED", True)
    mocker.patch.object(_boot.setting, "DEVICE_ID", "")
    mocker.patch.object(_boot.setting, "CLAIM_CODE", "")
    mocker.patch("_boot.gc")
    mocker.patch("_boot.ResetService")
    guard_cls = mocker.patch("_boot.BootLoopGuard")
    guard_cls.return_value.check.return_value = False
    mock_main = MagicMock()
    mocker.patch.dict("sys.modules", {"main": mock_main})

    _boot.run_bootstrap()

    mock_main.start_claim.assert_not_called()
    mock_main.start.assert_called_once_with()


def test_run_bootstrap_opens_serial_interrupt_window_when_enabled(mocker):
    mocker.patch.object(_boot.setting, "WIFI_SSID", "TestNet")
    mocker.patch.object(_boot.setting, "BOOT_INTERRUPT_WINDOW_SECONDS", 3)
    order = []
    gc_mock = mocker.patch("_boot.gc")
    gc_mock.collect.side_effect = lambda: order.append("gc.collect")
    reset_service_cls = mocker.patch("_boot.ResetService")
    reset_service_cls.return_value.read.side_effect = lambda: order.append("reset.read")
    guard_cls = mocker.patch("_boot.BootLoopGuard")
    guard_cls.return_value.check.side_effect = (
        lambda: order.append("guard.check") or False
    )
    mocker.patch.object(
        _boot.time,
        "sleep",
        side_effect=lambda seconds: order.append(f"sleep:{seconds}"),
    )
    mock_main = MagicMock()
    mock_main.start.side_effect = lambda: order.append("main.start")
    mocker.patch.dict("sys.modules", {"main": mock_main})

    _boot.run_bootstrap()

    assert order == [
        "gc.collect",
        "reset.read",
        "guard.check",
        "gc.collect",
        "sleep:3",
        "main.start",
    ]
