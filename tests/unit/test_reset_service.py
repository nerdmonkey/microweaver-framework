from unittest.mock import MagicMock

from app.services.reset import ResetService


def test_read_logs_watchdog_trip(mocker):
    mock_esp32 = mocker.patch("app.services.reset.esp32")
    mock_esp32.reset_reason.return_value = mock_esp32.TG0WDT_SYS_RESET
    logger = MagicMock()

    service = ResetService(logger=logger)
    service.read()

    logger.log.assert_called_once_with(
        "watchdog_trip", level="warning", reason="watchdog"
    )


def test_read_logs_non_watchdog_reset(mocker):
    mock_esp32 = mocker.patch("app.services.reset.esp32")
    mock_esp32.reset_reason.return_value = mock_esp32.POWERON_RESET
    logger = MagicMock()

    service = ResetService(logger=logger)
    service.read()

    logger.log.assert_called_once_with("reset", reason="power_on")


def test_read_labels_power_on_reset(mocker):
    mock_esp32 = mocker.patch("app.services.reset.esp32")
    mock_esp32.reset_reason.return_value = mock_esp32.POWERON_RESET

    service = ResetService()
    result = service.read()

    assert result == "power_on"
    assert service.reason == "power_on"


def test_read_labels_brownout_reset(mocker):
    mock_esp32 = mocker.patch("app.services.reset.esp32")
    mock_esp32.reset_reason.return_value = mock_esp32.RTCWDT_BROWN_OUT_RESET

    service = ResetService()
    result = service.read()

    assert result == "brownout"


def test_read_labels_deepsleep_reset(mocker):
    mock_esp32 = mocker.patch("app.services.reset.esp32")
    mock_esp32.reset_reason.return_value = mock_esp32.DEEPSLEEP_RESET

    service = ResetService()
    result = service.read()

    assert result == "deep_sleep"


def test_read_labels_watchdog_variants(mocker):
    mock_esp32 = mocker.patch("app.services.reset.esp32")
    for constant_name in (
        "OWDT_RESET",
        "TG0WDT_SYS_RESET",
        "TG1WDT_SYS_RESET",
        "RTCWDT_SYS_RESET",
        "TGWDT_CPU_RESET",
        "RTCWDT_CPU_RESET",
        "RTCWDT_RTC_RESET",
    ):
        mock_esp32.reset_reason.return_value = getattr(mock_esp32, constant_name)

        service = ResetService()
        result = service.read()

        assert result == "watchdog"


def test_read_labels_software_reset_variants(mocker):
    mock_esp32 = mocker.patch("app.services.reset.esp32")
    for constant_name in ("SW_RESET", "SW_CPU_RESET"):
        mock_esp32.reset_reason.return_value = getattr(mock_esp32, constant_name)

        service = ResetService()
        result = service.read()

        assert result == "software"


def test_read_labels_sdio_reset(mocker):
    mock_esp32 = mocker.patch("app.services.reset.esp32")
    mock_esp32.reset_reason.return_value = mock_esp32.SDIO_RESET

    service = ResetService()
    result = service.read()

    assert result == "sdio"


def test_read_labels_intrusion_reset(mocker):
    mock_esp32 = mocker.patch("app.services.reset.esp32")
    mock_esp32.reset_reason.return_value = mock_esp32.INTRUSION_RESET

    service = ResetService()
    result = service.read()

    assert result == "intrusion"


def test_read_labels_external_reset(mocker):
    mock_esp32 = mocker.patch("app.services.reset.esp32")
    mock_esp32.reset_reason.return_value = mock_esp32.EXT_CPU_RESET

    service = ResetService()
    result = service.read()

    assert result == "external"


def test_read_labels_unknown_reset_cause(mocker):
    mock_esp32 = mocker.patch("app.services.reset.esp32")
    mock_esp32.reset_reason.return_value = "some_unmapped_value"

    service = ResetService()
    result = service.read()

    assert result == "unknown"


def test_reason_is_none_before_read():
    service = ResetService()

    assert service.reason is None
