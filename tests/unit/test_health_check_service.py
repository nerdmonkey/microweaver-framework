from unittest.mock import MagicMock

from app.services.health import HealthCheckService


def test_poll_records_healthy_status_for_passing_check(mocker):
    mocker.patch("time.time", return_value=100)
    service = HealthCheckService()
    service.register("wifi", lambda: True)

    status = service.poll()

    assert status == {"wifi": {"healthy": True, "error": None, "checked_at": 100}}


def test_poll_records_unhealthy_status_for_failing_check(mocker):
    mocker.patch("time.time", return_value=100)
    service = HealthCheckService()
    service.register("wifi", lambda: False)

    status = service.poll()

    assert status["wifi"]["healthy"] is False


def test_poll_logs_when_check_fails(mocker):
    mocker.patch("time.time", return_value=100)
    logger = MagicMock()
    service = HealthCheckService(logger=logger)
    service.register("wifi", lambda: False)

    service.poll()

    logger.log.assert_called_once_with(
        "health_check_failed", level="warning", service="wifi", error=None
    )


def test_poll_records_error_when_check_raises(mocker):
    mocker.patch("time.time", return_value=100)
    service = HealthCheckService()
    service.register("mqtt", MagicMock(side_effect=OSError("broker down")))

    status = service.poll()

    assert status["mqtt"] == {
        "healthy": False,
        "error": "broker down",
        "checked_at": 100,
    }


def test_poll_logs_error_when_check_raises(mocker):
    mocker.patch("time.time", return_value=100)
    logger = MagicMock()
    service = HealthCheckService(logger=logger)
    service.register("mqtt", MagicMock(side_effect=OSError("broker down")))

    service.poll()

    logger.log.assert_called_once_with(
        "health_check_failed", level="warning", service="mqtt", error="broker down"
    )


def test_poll_does_not_log_when_check_passes(mocker):
    mocker.patch("time.time", return_value=100)
    logger = MagicMock()
    service = HealthCheckService(logger=logger)
    service.register("wifi", lambda: True)

    service.poll()

    logger.log.assert_not_called()


def test_poll_skips_until_interval_elapses(mocker):
    check = MagicMock(return_value=True)
    mocker.patch("time.time", side_effect=[100, 110, 131])
    service = HealthCheckService(interval_seconds=30)
    service.register("wifi", check)

    service.poll()
    service.poll()
    service.poll()

    assert check.call_count == 2


def test_checks_can_be_passed_in_constructor(mocker):
    mocker.patch("time.time", return_value=100)
    service = HealthCheckService(checks={"wifi": lambda: True})

    status = service.poll()

    assert status["wifi"]["healthy"] is True


def test_is_healthy_true_when_all_checks_pass(mocker):
    mocker.patch("time.time", return_value=100)
    service = HealthCheckService()
    service.register("wifi", lambda: True)
    service.register("mqtt", lambda: True)
    service.poll()

    assert service.is_healthy() is True


def test_is_healthy_false_when_any_check_fails(mocker):
    mocker.patch("time.time", return_value=100)
    service = HealthCheckService()
    service.register("wifi", lambda: True)
    service.register("mqtt", lambda: False)
    service.poll()

    assert service.is_healthy() is False


def test_is_healthy_true_when_no_checks_registered():
    service = HealthCheckService()

    assert service.is_healthy() is True


def test_report_includes_app_version_and_health_summary(mocker):
    mocker.patch("time.time", return_value=100)
    service = HealthCheckService(app_version="1.2.3")
    service.register("wifi", lambda: True)
    service.poll()

    assert service.report() == {
        "app_version": "1.2.3",
        "healthy": True,
        "checks": {"wifi": {"healthy": True, "error": None, "checked_at": 100}},
    }


def test_app_version_defaults_to_empty_string():
    service = HealthCheckService()

    assert service.app_version == ""


def test_needs_update_true_when_candidate_is_newer():
    service = HealthCheckService(app_version="1.2.3")

    assert service.needs_update("1.3.0") is True


def test_needs_update_false_when_candidate_is_older():
    service = HealthCheckService(app_version="1.2.3")

    assert service.needs_update("1.2.0") is False


def test_needs_update_false_when_candidate_is_equal():
    service = HealthCheckService(app_version="1.2.3")

    assert service.needs_update("1.2.3") is False


def test_needs_update_handles_different_version_lengths():
    service = HealthCheckService(app_version="1.2")

    assert service.needs_update("1.2.1") is True
    assert service.needs_update("1.2.0") is False


def test_needs_update_treats_non_numeric_segments_as_zero():
    service = HealthCheckService(app_version="1.2.3-beta")

    assert service.needs_update("1.2.4") is True
    assert service.needs_update("1.2.0") is False


def test_report_omits_metrics_when_none_given(mocker):
    mocker.patch("time.time", return_value=100)
    service = HealthCheckService()

    assert "metrics" not in service.report()


def test_report_includes_metrics_snapshot_when_given(mocker):
    mocker.patch("time.time", return_value=100)
    metrics = MagicMock()
    metrics.snapshot.return_value = {
        "uptime_seconds": 30,
        "messages_published": 2,
        "messages_received": 1,
        "errors": 0,
    }
    service = HealthCheckService(metrics=metrics)

    assert service.report()["metrics"] == metrics.snapshot.return_value
