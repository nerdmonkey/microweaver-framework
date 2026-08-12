from app.services.ntp import NtpSyncService


def test_sync_sets_host_and_timeout_then_calls_settime(mocker):
    mock_ntptime = mocker.patch("app.services.ntp.ntptime")

    service = NtpSyncService(server="time.example.com", timeout_seconds=3)
    service.sync()

    assert mock_ntptime.host == "time.example.com"
    assert mock_ntptime.timeout == 3
    mock_ntptime.settime.assert_called_once_with()


def test_sync_skips_timeout_assignment_when_ntptime_lacks_it(mocker):
    mock_ntptime = mocker.patch(
        "app.services.ntp.ntptime", mocker.MagicMock(spec=["host", "settime"])
    )

    service = NtpSyncService(server="time.example.com", timeout_seconds=3)
    service.sync()

    assert mock_ntptime.host == "time.example.com"
    assert not hasattr(mock_ntptime, "timeout")
    mock_ntptime.settime.assert_called_once_with()


def test_sync_propagates_settime_failure(mocker):
    mock_ntptime = mocker.patch("app.services.ntp.ntptime")
    mock_ntptime.settime.side_effect = OSError("timed out")

    service = NtpSyncService()

    try:
        service.sync()
        assert False, "expected OSError to propagate"
    except OSError as e:
        assert str(e) == "timed out"


def test_default_server_and_timeout():
    service = NtpSyncService()

    assert service.server == "pool.ntp.org"
    assert service.timeout_seconds == 5
