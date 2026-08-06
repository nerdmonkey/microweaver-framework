from unittest.mock import MagicMock

from app.services.error_handler import ErrorHandlerService


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
        "unhandled_exception", level="error", context="ctx", error="boom"
    )
