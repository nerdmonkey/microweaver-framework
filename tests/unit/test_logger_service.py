import json

from app.services.logger import LogService


def test_log_emits_json_by_default(mocker, capsys):
    mocker.patch("time.time", return_value=100)
    service = LogService()

    service.log("memory_warning", level="warning", free_bytes=500)

    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload == {
        "event": "memory_warning",
        "level": "warning",
        "ts": 100,
        "free_bytes": 500,
    }


def test_log_defaults_to_info_level(mocker, capsys):
    mocker.patch("time.time", return_value=100)
    service = LogService()

    service.log("reset")

    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["level"] == "info"


def test_log_emits_key_value_pairs_when_format_is_kv(mocker, capsys):
    mocker.patch("time.time", return_value=100)
    service = LogService(format="kv")

    service.log("watchdog_trip", level="warning", reason="watchdog")

    out = capsys.readouterr().out.strip()
    assert "event=watchdog_trip" in out
    assert "level=warning" in out
    assert "ts=100" in out
    assert "reason=watchdog" in out


def test_log_quotes_kv_values_containing_spaces(mocker, capsys):
    mocker.patch("time.time", return_value=100)
    service = LogService(format="kv")

    service.log("health_check_failed", service="mqtt", error="broker down")

    out = capsys.readouterr().out.strip()
    assert 'error="broker down"' in out


def test_log_suppresses_entries_below_configured_level(mocker, capsys):
    mocker.patch("time.time", return_value=100)
    service = LogService(level="warning")

    service.log("debug_probe", level="debug")
    service.log("routine_tick", level="info")

    assert capsys.readouterr().out == ""


def test_log_emits_entries_at_or_above_configured_level(mocker, capsys):
    mocker.patch("time.time", return_value=100)
    service = LogService(level="warning")

    service.log("watchdog_trip", level="warning")
    service.log("mqtt_failure", level="error")

    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 2


def test_log_defaults_to_info_level_threshold(mocker, capsys):
    mocker.patch("time.time", return_value=100)
    service = LogService()

    service.log("debug_probe", level="debug")
    service.log("reset")

    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1


def test_log_treats_unknown_level_as_info(mocker, capsys):
    mocker.patch("time.time", return_value=100)
    service = LogService(level="bogus")

    service.log("reset", level="bogus")

    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["level"] == "bogus"
