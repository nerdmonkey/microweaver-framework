from unittest.mock import MagicMock

from app.services.reset import ResetService


def test_read_logs_watchdog_trip(mocker):
    mock_machine = mocker.patch("app.services.reset.machine")
    mock_machine.reset_cause.return_value = mock_machine.WDT_RESET
    logger = MagicMock()

    service = ResetService(logger=logger)
    service.read()

    logger.log.assert_called_once_with(
        "watchdog_trip", level="warning", reason="watchdog"
    )


def test_read_logs_non_watchdog_reset(mocker):
    mock_machine = mocker.patch("app.services.reset.machine")
    mock_machine.reset_cause.return_value = mock_machine.PWRON_RESET
    logger = MagicMock()

    service = ResetService(logger=logger)
    service.read()

    logger.log.assert_called_once_with("reset", reason="power_on")


def test_read_labels_power_on_reset(mocker):
    mock_machine = mocker.patch("app.services.reset.machine")
    mock_machine.reset_cause.return_value = mock_machine.PWRON_RESET

    service = ResetService()
    result = service.read()

    assert result == "power_on"
    assert service.reason == "power_on"


def test_read_labels_hard_reset(mocker):
    mock_machine = mocker.patch("app.services.reset.machine")
    mock_machine.reset_cause.return_value = mock_machine.HARD_RESET

    service = ResetService()
    result = service.read()

    assert result == "hard_reset"


def test_read_labels_deepsleep_reset(mocker):
    mock_machine = mocker.patch("app.services.reset.machine")
    mock_machine.reset_cause.return_value = mock_machine.DEEPSLEEP_RESET

    service = ResetService()
    result = service.read()

    assert result == "deep_sleep"


def test_read_labels_software_reset(mocker):
    mock_machine = mocker.patch("app.services.reset.machine")
    mock_machine.reset_cause.return_value = mock_machine.SOFT_RESET

    service = ResetService()
    result = service.read()

    assert result == "software"


def test_read_labels_unknown_reset_cause(mocker):
    mock_machine = mocker.patch("app.services.reset.machine")
    mock_machine.reset_cause.return_value = "some_unmapped_value"

    service = ResetService()
    result = service.read()

    assert result == "unknown"


def test_read_falls_back_when_reset_cause_unavailable(mocker):
    mock_machine = mocker.patch("app.services.reset.machine")
    del mock_machine.reset_cause
    logger = MagicMock()

    service = ResetService(logger=logger)
    result = service.read()

    assert result == "unknown"
    logger.log.assert_called_once_with("reset", reason="unknown")


def test_reason_is_none_before_read():
    service = ResetService()

    assert service.reason is None


def test_read_recovers_and_clears_crash_log_when_present(mocker):
    mock_machine = mocker.patch("app.services.reset.machine")
    mock_machine.reset_cause.return_value = mock_machine.PWRON_RESET
    logger = MagicMock()
    crash_log = MagicMock()
    crash_log.read.return_value = {
        "event": "unhandled_exception",
        "ts": 100,
        "context": "mqtt_connect",
        "error": "boom",
        "trace": "OSError: boom",
    }

    service = ResetService(logger=logger, crash_log=crash_log)
    service.read()

    logger.log.assert_called_with(
        "crash_log_recovered",
        level="error",
        ts=100,
        context="mqtt_connect",
        error="boom",
        trace="OSError: boom",
        original_event="unhandled_exception",
    )
    crash_log.clear.assert_called_once_with()


def test_read_skips_recovery_when_crash_log_empty(mocker):
    mock_machine = mocker.patch("app.services.reset.machine")
    mock_machine.reset_cause.return_value = mock_machine.PWRON_RESET
    logger = MagicMock()
    crash_log = MagicMock()
    crash_log.read.return_value = None

    service = ResetService(logger=logger, crash_log=crash_log)
    service.read()

    assert logger.log.call_args_list == [mocker.call("reset", reason="power_on")]
    crash_log.clear.assert_not_called()


def test_read_skips_recovery_when_no_crash_log_given(mocker):
    mock_machine = mocker.patch("app.services.reset.machine")
    mock_machine.reset_cause.return_value = mock_machine.PWRON_RESET
    logger = MagicMock()

    service = ResetService(logger=logger)
    service.read()

    assert logger.log.call_args_list == [mocker.call("reset", reason="power_on")]
