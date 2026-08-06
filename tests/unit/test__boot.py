from unittest.mock import MagicMock

import pytest

import _boot


def test_run_bootstrap_orders_gc_reset_guard_import_gc_start(mocker):
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
