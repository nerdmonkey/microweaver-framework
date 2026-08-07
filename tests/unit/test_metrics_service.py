from app.services.metrics import MetricsService


def make_metrics_service(mocker, start_time):
    mocker.patch("time.time", return_value=start_time)
    return MetricsService()


def test_start_time_recorded_at_construction(mocker):
    service = make_metrics_service(mocker, 100)

    assert service.start_time == 100


def test_uptime_seconds_measures_elapsed_time(mocker):
    mocker.patch("time.time", side_effect=[100, 150])
    service = MetricsService()

    assert service.uptime_seconds() == 50


def test_record_publish_increments_messages_published(mocker):
    service = make_metrics_service(mocker, 100)

    service.record_publish()
    service.record_publish()

    assert service.messages_published == 2


def test_record_message_increments_messages_received(mocker):
    service = make_metrics_service(mocker, 100)

    service.record_message()

    assert service.messages_received == 1


def test_record_error_increments_errors(mocker):
    service = make_metrics_service(mocker, 100)

    service.record_error()

    assert service.errors == 1


def test_counters_start_at_zero(mocker):
    service = make_metrics_service(mocker, 100)

    assert service.messages_published == 0
    assert service.messages_received == 0
    assert service.errors == 0


def test_snapshot_reports_all_counters(mocker):
    mocker.patch("time.time", side_effect=[100, 130])
    service = MetricsService()
    service.record_publish()
    service.record_message()
    service.record_error()

    assert service.snapshot() == {
        "uptime_seconds": 30,
        "messages_published": 1,
        "messages_received": 1,
        "errors": 1,
    }
