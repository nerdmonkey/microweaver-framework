from unittest.mock import MagicMock

from app.services.poll_scheduler import PollScheduler


def test_is_due_true_when_never_polled():
    scheduler = PollScheduler()

    assert scheduler.is_due("dht22") is True


def test_is_due_false_before_interval_elapses(mocker):
    mocker.patch("time.time", side_effect=[100, 110])
    scheduler = PollScheduler(interval_seconds=30)

    scheduler.mark_polled("dht22")

    assert scheduler.is_due("dht22") is False


def test_is_due_true_after_interval_elapses(mocker):
    mocker.patch("time.time", side_effect=[100, 131])
    scheduler = PollScheduler(interval_seconds=30)

    scheduler.mark_polled("dht22")

    assert scheduler.is_due("dht22") is True


def test_register_sets_per_name_interval(mocker):
    mocker.patch("time.time", side_effect=[100, 105])
    scheduler = PollScheduler(interval_seconds=30)
    scheduler.register("fast_sensor", interval_seconds=5)

    scheduler.mark_polled("fast_sensor")

    assert scheduler.is_due("fast_sensor") is True


def test_register_without_interval_falls_back_to_default(mocker):
    mocker.patch("time.time", side_effect=[100, 110])
    scheduler = PollScheduler(interval_seconds=30)
    scheduler.register("wifi_sensor")

    scheduler.mark_polled("wifi_sensor")

    assert scheduler.is_due("wifi_sensor") is False


def test_names_are_tracked_independently(mocker):
    mocker.patch("time.time", side_effect=[100, 100, 110])
    scheduler = PollScheduler(interval_seconds=30)

    scheduler.mark_polled("dht22")
    scheduler.mark_polled("relay")

    assert scheduler.is_due("dht22") is False


def test_poll_calls_read_and_returns_value_when_due(mocker):
    mocker.patch("time.time", return_value=100)
    scheduler = PollScheduler()
    read = MagicMock(return_value=(21.5, 40))

    value = scheduler.poll("dht22", read)

    read.assert_called_once()
    assert value == (21.5, 40)


def test_poll_marks_polled_after_successful_read(mocker):
    mocker.patch("time.time", side_effect=[100, 110])
    scheduler = PollScheduler(interval_seconds=30)
    read = MagicMock(return_value=1)

    scheduler.poll("dht22", read)

    assert scheduler.is_due("dht22") is False


def test_poll_skips_read_when_not_due(mocker):
    mocker.patch("time.time", side_effect=[100, 110])
    scheduler = PollScheduler(interval_seconds=30)
    read = MagicMock(return_value=1)

    scheduler.poll("dht22", read)
    result = scheduler.poll("dht22", read)

    read.assert_called_once()
    assert result is None
