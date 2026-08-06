from app.services.watchdog import WatchdogService


def test_start_creates_wdt_with_configured_timeout(mocker):
    mock_wdt_cls = mocker.patch("app.services.watchdog.WDT")
    mock_wdt = mock_wdt_cls.return_value

    service = WatchdogService(timeout_ms=5000)
    result = service.start()

    mock_wdt_cls.assert_called_once_with(timeout=5000)
    assert result is mock_wdt
    assert service.wdt is mock_wdt


def test_start_is_idempotent(mocker):
    mock_wdt_cls = mocker.patch("app.services.watchdog.WDT")

    service = WatchdogService(timeout_ms=5000)
    service.start()
    service.start()

    mock_wdt_cls.assert_called_once_with(timeout=5000)


def test_feed_delegates_to_wdt_once_started(mocker):
    mocker.patch("app.services.watchdog.WDT")
    service = WatchdogService(timeout_ms=5000)
    service.start()

    service.feed()

    service.wdt.feed.assert_called_once_with()


def test_feed_without_start_is_noop():
    service = WatchdogService(timeout_ms=5000)

    service.feed()
