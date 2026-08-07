from unittest.mock import MagicMock

from app.services.error_handler import ErrorHandlerService, format_exception


def test_guard_returns_function_result_on_success():
    service = ErrorHandlerService(logger=MagicMock())

    result = service.guard(lambda: 42, "some_context")

    assert result == 42


def test_guard_passes_through_args_and_kwargs():
    service = ErrorHandlerService(logger=MagicMock())
    fn = MagicMock(return_value="ok")

    result = service.guard(fn, "some_context", 1, 2, key="value")

    fn.assert_called_once_with(1, 2, key="value")
    assert result == "ok"


def test_guard_swallows_exception_and_returns_none():
    service = ErrorHandlerService(logger=MagicMock())

    def failing():
        raise OSError("broker down")

    result = service.guard(failing, "mqtt_connect")

    assert result is None


def test_guard_logs_exception_with_context():
    logger = MagicMock()
    service = ErrorHandlerService(logger=logger)

    def failing():
        raise OSError("broker down")

    service.guard(failing, "mqtt_connect")

    logger.log.assert_called_once_with(
        "unhandled_exception",
        level="error",
        context="mqtt_connect",
        error="broker down",
        trace="OSError: broker down",
    )


def test_guard_does_not_log_on_success():
    logger = MagicMock()
    service = ErrorHandlerService(logger=logger)

    service.guard(lambda: 1, "some_context")

    logger.log.assert_not_called()


def test_uses_default_logger_when_none_given(mocker):
    mock_logger_cls = mocker.patch("app.services.error_handler.LogService")
    mock_logger = mock_logger_cls.return_value

    service = ErrorHandlerService()
    service.guard(lambda: (_ for _ in ()).throw(RuntimeError("boom")), "ctx")

    assert service.logger is mock_logger
    mock_logger.log.assert_called_once_with(
        "unhandled_exception",
        level="error",
        context="ctx",
        error="boom",
        trace="RuntimeError: boom",
    )


def test_format_exception_uses_sys_print_exception_when_available(mocker):
    def fake_print_exception(exc, buf):
        buf.write("Traceback (most recent call last):\nOSError: broker down")

    mocker.patch(
        "app.services.error_handler.sys.print_exception",
        create=True,
        side_effect=fake_print_exception,
    )

    result = format_exception(OSError("broker down"))

    assert result == "Traceback (most recent call last):\nOSError: broker down"


def test_format_exception_falls_back_when_sys_print_exception_unavailable():
    result = format_exception(OSError("broker down"))

    assert result == "OSError: broker down"


def test_guard_writes_crash_log_on_exception():
    crash_log = MagicMock()
    service = ErrorHandlerService(logger=MagicMock(), crash_log=crash_log)

    def failing():
        raise OSError("broker down")

    service.guard(failing, "mqtt_connect")

    crash_log.write.assert_called_once_with(
        "unhandled_exception",
        context="mqtt_connect",
        error="broker down",
        trace="OSError: broker down",
    )


def test_guard_does_not_write_crash_log_on_success():
    crash_log = MagicMock()
    service = ErrorHandlerService(logger=MagicMock(), crash_log=crash_log)

    service.guard(lambda: 1, "some_context")

    crash_log.write.assert_not_called()


def test_guard_does_not_touch_crash_log_when_none_given():
    service = ErrorHandlerService(logger=MagicMock())

    def failing():
        raise OSError("broker down")

    result = service.guard(failing, "mqtt_connect")

    assert result is None
