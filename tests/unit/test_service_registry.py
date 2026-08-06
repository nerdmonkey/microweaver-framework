from unittest.mock import MagicMock

from app.services.registry import ServiceRegistry


def test_register_returns_self_for_chaining():
    registry = ServiceRegistry()

    result = registry.register("a")

    assert result is registry


def test_start_all_calls_starts_in_registration_order(mocker):
    calls = []
    registry = ServiceRegistry()
    registry.register("a", start=lambda: calls.append("a"))
    registry.register("b", start=lambda: calls.append("b"))

    registry.start_all()

    assert calls == ["a", "b"]


def test_start_all_skips_entries_without_start():
    registry = ServiceRegistry()
    registry.register("a")

    registry.start_all()


def test_stop_all_calls_stops_in_reverse_order():
    calls = []
    registry = ServiceRegistry()
    registry.register("a", stop=lambda: calls.append("a"))
    registry.register("b", stop=lambda: calls.append("b"))

    registry.stop_all()

    assert calls == ["b", "a"]


def test_stop_all_skips_entries_without_stop():
    registry = ServiceRegistry()
    registry.register("a")

    registry.stop_all()


def test_stop_all_continues_after_a_failing_stop(mocker):
    print_spy = mocker.patch("builtins.print")
    calls = []
    registry = ServiceRegistry()

    def failing_stop():
        raise RuntimeError("boom")

    registry.register("a", stop=failing_stop)
    registry.register("b", stop=lambda: calls.append("b"))

    registry.stop_all()

    assert calls == ["b"]
    assert print_spy.call_args_list == [
        mocker.call("Failed to stop service:", "a", "-", mocker.ANY)
    ]


def test_start_all_continues_after_a_failing_start(mocker):
    print_spy = mocker.patch("builtins.print")
    calls = []
    registry = ServiceRegistry()

    def failing_start():
        raise RuntimeError("boom")

    registry.register("a", start=failing_start)
    registry.register("b", start=lambda: calls.append("b"))

    registry.start_all()

    assert calls == ["b"]
    assert print_spy.call_args_list == [
        mocker.call("Failed to start service:", "a", "-", mocker.ANY)
    ]


def test_start_all_routes_failure_through_error_handler_when_given():
    error_handler = MagicMock()
    registry = ServiceRegistry(error_handler=error_handler)

    def failing_start():
        raise RuntimeError("boom")

    registry.register("watchdog", start=failing_start)

    registry.start_all()

    error_handler.guard.assert_called_once_with(failing_start, "service_start:watchdog")


def test_stop_all_routes_failure_through_error_handler_when_given():
    error_handler = MagicMock()
    registry = ServiceRegistry(error_handler=error_handler)

    def failing_stop():
        raise RuntimeError("boom")

    registry.register("watchdog", stop=failing_stop)

    registry.stop_all()

    error_handler.guard.assert_called_once_with(failing_stop, "service_stop:watchdog")
