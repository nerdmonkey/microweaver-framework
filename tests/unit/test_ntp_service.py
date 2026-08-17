from app.services.ntp import NtpService


def test_sync_succeeds_on_first_try(mocker):
    mock_ntptime = mocker.patch("app.services.ntp.ntptime")

    service = NtpService(host="time.example.org")
    result = service.sync()

    assert result is True
    assert mock_ntptime.host == "time.example.org"
    mock_ntptime.settime.assert_called_once_with()


def test_sync_retries_then_succeeds(mocker):
    mock_ntptime = mocker.patch("app.services.ntp.ntptime")
    mock_ntptime.settime.side_effect = [OSError("timed out"), None]
    mock_sleep = mocker.patch("time.sleep")

    service = NtpService(sync_attempts=3, retry_delay_seconds=1)
    result = service.sync()

    assert result is True
    assert mock_ntptime.settime.call_count == 2
    mock_sleep.assert_called_once_with(1)


def test_sync_returns_false_after_exhausting_attempts(mocker):
    mock_ntptime = mocker.patch("app.services.ntp.ntptime")
    mock_ntptime.settime.side_effect = OSError("timed out")
    mock_sleep = mocker.patch("time.sleep")

    service = NtpService(sync_attempts=3, retry_delay_seconds=1)
    result = service.sync()

    assert result is False
    assert mock_ntptime.settime.call_count == 3
    assert mock_sleep.call_count == 2
