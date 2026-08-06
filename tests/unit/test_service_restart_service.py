from unittest.mock import MagicMock

from app.services.service_restart import ServiceRestartService


def test_reconcile_restarts_unhealthy_service():
    restart = MagicMock()
    service = ServiceRestartService()
    service.register("wifi", restart)

    restarted = service.reconcile({"wifi": {"healthy": False, "error": "timeout"}})

    restart.assert_called_once_with()
    assert restarted == ["wifi"]


def test_reconcile_skips_healthy_service():
    restart = MagicMock()
    service = ServiceRestartService()
    service.register("wifi", restart)

    restarted = service.reconcile({"wifi": {"healthy": True, "error": None}})

    restart.assert_not_called()
    assert restarted == []


def test_reconcile_skips_service_without_registered_restart():
    service = ServiceRestartService()

    restarted = service.reconcile({"mqtt": {"healthy": False, "error": "down"}})

    assert restarted == []


def test_reconcile_survives_restart_exception():
    restart = MagicMock(side_effect=OSError("still down"))
    service = ServiceRestartService()
    service.register("wifi", restart)

    restarted = service.reconcile({"wifi": {"healthy": False, "error": "timeout"}})

    restart.assert_called_once_with()
    assert restarted == []


def test_reconcile_stops_after_max_attempts():
    restart = MagicMock()
    service = ServiceRestartService(max_attempts=2)
    service.register("wifi", restart)
    status = {"wifi": {"healthy": False, "error": "timeout"}}

    service.reconcile(status)
    service.reconcile(status)
    service.reconcile(status)

    assert restart.call_count == 2


def test_reconcile_resets_attempts_once_healthy_again():
    restart = MagicMock()
    service = ServiceRestartService(max_attempts=1)
    service.register("wifi", restart)

    service.reconcile({"wifi": {"healthy": False, "error": "timeout"}})
    service.reconcile({"wifi": {"healthy": True, "error": None}})
    service.reconcile({"wifi": {"healthy": False, "error": "timeout"}})

    assert restart.call_count == 2


def test_restarts_can_be_passed_in_constructor():
    restart = MagicMock()
    service = ServiceRestartService(restarts={"wifi": restart})

    service.reconcile({"wifi": {"healthy": False, "error": "timeout"}})

    restart.assert_called_once_with()
