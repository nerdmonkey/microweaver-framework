from app.services.memory_monitor import MemoryMonitorService


def test_check_returns_false_when_free_memory_above_threshold(mocker):
    mocker.patch(
        "app.services.memory_monitor.gc.mem_free", return_value=20000, create=True
    )
    service = MemoryMonitorService(threshold_bytes=10000)

    result = service.check()

    assert result is False


def test_check_returns_true_and_logs_when_below_threshold(mocker, capsys):
    mocker.patch(
        "app.services.memory_monitor.gc.mem_free", return_value=5000, create=True
    )
    service = MemoryMonitorService(threshold_bytes=10000, action="log")

    result = service.check()

    assert result is True
    out = capsys.readouterr().out
    assert "MEMORY" in out
    assert "5000" in out


def test_check_warns_when_action_is_warn(mocker, capsys):
    mocker.patch(
        "app.services.memory_monitor.gc.mem_free", return_value=5000, create=True
    )
    service = MemoryMonitorService(threshold_bytes=10000, action="warn")

    service.check()

    out = capsys.readouterr().out
    assert "MEMORY WARNING" in out


def test_check_restarts_when_action_is_restart(mocker):
    mocker.patch(
        "app.services.memory_monitor.gc.mem_free", return_value=5000, create=True
    )
    mock_reset = mocker.patch("app.services.memory_monitor.reset")
    service = MemoryMonitorService(threshold_bytes=10000, action="restart")

    service.check()

    mock_reset.assert_called_once_with()


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


def test_default_action_is_log(mocker, capsys):
    mocker.patch(
        "app.services.memory_monitor.gc.mem_free", return_value=5000, create=True
    )
    service = MemoryMonitorService(threshold_bytes=10000)

    service.check()

    out = capsys.readouterr().out
    assert "MEMORY:" in out
    assert "WARNING" not in out
