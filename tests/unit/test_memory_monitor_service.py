from unittest.mock import MagicMock

from app.services.memory_monitor import MemoryMonitorService


def test_check_returns_false_when_free_memory_above_threshold(mocker):
    mocker.patch(
        "app.services.memory_monitor.gc.mem_free", return_value=20000, create=True
    )
    service = MemoryMonitorService(threshold_bytes=10000)

    result = service.check()

    assert result is False


def test_check_returns_true_and_logs_when_below_threshold(mocker):
    mocker.patch(
        "app.services.memory_monitor.gc.mem_free", return_value=5000, create=True
    )
    logger = MagicMock()
    service = MemoryMonitorService(threshold_bytes=10000, action="log", logger=logger)

    result = service.check()

    assert result is True
    logger.log.assert_called_once_with(
        "memory_warning",
        level="info",
        free_bytes=5000,
        threshold_bytes=10000,
        action="log",
    )


def test_check_warns_when_action_is_warn(mocker):
    mocker.patch(
        "app.services.memory_monitor.gc.mem_free", return_value=5000, create=True
    )
    logger = MagicMock()
    service = MemoryMonitorService(threshold_bytes=10000, action="warn", logger=logger)

    service.check()

    logger.log.assert_called_once_with(
        "memory_warning",
        level="warning",
        free_bytes=5000,
        threshold_bytes=10000,
        action="warn",
    )


def test_check_restarts_when_action_is_restart(mocker):
    mocker.patch(
        "app.services.memory_monitor.gc.mem_free", return_value=5000, create=True
    )
    mock_reset = mocker.patch("app.services.memory_monitor.reset")
    service = MemoryMonitorService(threshold_bytes=10000, action="restart")

    service.check()

    mock_reset.assert_called_once_with()


def test_check_logs_before_restarting(mocker):
    mocker.patch(
        "app.services.memory_monitor.gc.mem_free", return_value=5000, create=True
    )
    mocker.patch("app.services.memory_monitor.reset")
    logger = MagicMock()
    service = MemoryMonitorService(
        threshold_bytes=10000, action="restart", logger=logger
    )

    service.check()

    logger.log.assert_called_once_with(
        "memory_warning",
        level="info",
        free_bytes=5000,
        threshold_bytes=10000,
        action="restart",
    )


def test_check_does_not_restart_when_above_threshold(mocker):
    mocker.patch(
        "app.services.memory_monitor.gc.mem_free", return_value=20000, create=True
    )
    mock_reset = mocker.patch("app.services.memory_monitor.reset")
    service = MemoryMonitorService(threshold_bytes=10000, action="restart")

    service.check()

    mock_reset.assert_not_called()


def test_free_bytes_delegates_to_gc(mocker):
    mocker.patch(
        "app.services.memory_monitor.gc.mem_free", return_value=42, create=True
    )
    service = MemoryMonitorService()

    assert service.free_bytes() == 42


def test_default_action_is_log(mocker):
    mocker.patch(
        "app.services.memory_monitor.gc.mem_free", return_value=5000, create=True
    )
    logger = MagicMock()
    service = MemoryMonitorService(threshold_bytes=10000, logger=logger)

    service.check()

    logger.log.assert_called_once_with(
        "memory_warning",
        level="info",
        free_bytes=5000,
        threshold_bytes=10000,
        action="log",
    )


def test_check_writes_crash_log_before_restarting(mocker):
    mocker.patch(
        "app.services.memory_monitor.gc.mem_free", return_value=5000, create=True
    )
    mocker.patch("app.services.memory_monitor.reset")
    crash_log = MagicMock()
    service = MemoryMonitorService(
        threshold_bytes=10000, action="restart", crash_log=crash_log
    )

    service.check()

    crash_log.write.assert_called_once_with(
        "memory_restart", free_bytes=5000, threshold_bytes=10000
    )


def test_check_does_not_write_crash_log_when_action_is_not_restart(mocker):
    mocker.patch(
        "app.services.memory_monitor.gc.mem_free", return_value=5000, create=True
    )
    crash_log = MagicMock()
    service = MemoryMonitorService(
        threshold_bytes=10000, action="log", crash_log=crash_log
    )

    service.check()

    crash_log.write.assert_not_called()


def test_check_restarts_without_crash_log_when_none_given(mocker):
    mocker.patch(
        "app.services.memory_monitor.gc.mem_free", return_value=5000, create=True
    )
    mock_reset = mocker.patch("app.services.memory_monitor.reset")
    service = MemoryMonitorService(threshold_bytes=10000, action="restart")

    service.check()

    mock_reset.assert_called_once_with()


def test_uses_default_logger_when_none_provided(mocker, capsys):
    mocker.patch(
        "app.services.memory_monitor.gc.mem_free", return_value=5000, create=True
    )
    mocker.patch("time.time", return_value=100)
    service = MemoryMonitorService(threshold_bytes=10000)

    service.check()

    out = capsys.readouterr().out
    assert "memory_warning" in out
