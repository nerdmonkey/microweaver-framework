from app.services.crash_log import CrashLogService


def make_service(tmp_path, enabled=True):
    path = str(tmp_path / "crash.json")
    return CrashLogService(path=path, enabled=enabled)


def test_write_persists_event_and_fields(tmp_path):
    service = make_service(tmp_path)

    service.write("unhandled_exception", context="mqtt_connect", error="boom")

    entry = service.read()
    assert entry["event"] == "unhandled_exception"
    assert entry["context"] == "mqtt_connect"
    assert entry["error"] == "boom"
    assert "ts" in entry


def test_write_is_noop_when_disabled(tmp_path):
    service = make_service(tmp_path, enabled=False)

    service.write("unhandled_exception", context="mqtt_connect")

    assert service.read() is None


def test_read_returns_none_when_file_missing(tmp_path):
    service = make_service(tmp_path)

    assert service.read() is None


def test_read_returns_none_when_file_corrupt(tmp_path):
    service = make_service(tmp_path)
    with open(service.path, "w") as crash_file:
        crash_file.write("not json")

    assert service.read() is None


def test_clear_removes_file(tmp_path):
    service = make_service(tmp_path)
    service.write("unhandled_exception", context="mqtt_connect")

    service.clear()

    assert service.read() is None


def test_clear_failure_is_printed_not_raised(tmp_path, capsys):
    service = make_service(tmp_path)

    service.clear()

    out = capsys.readouterr().out
    assert "Failed to clear crash log" in out


def test_write_failure_is_printed_not_raised(tmp_path, capsys):
    unwritable_path = str(tmp_path / "missing_dir" / "crash.json")
    service = CrashLogService(path=unwritable_path)

    service.write("unhandled_exception", context="mqtt_connect")

    out = capsys.readouterr().out
    assert "Failed to persist crash log" in out


def test_write_caps_file_size_when_entry_exceeds_max_bytes(tmp_path):
    path = str(tmp_path / "crash.json")
    service = CrashLogService(path=path, max_bytes=200)

    service.write(
        "unhandled_exception", context="mqtt_connect", error="boom", trace="x" * 5000
    )

    import os

    assert os.path.getsize(path) <= 200
    entry = service.read()
    assert entry["event"] == "unhandled_exception"
    assert entry["context"] == "mqtt_connect"
    assert entry["trace"].endswith("...[truncated]")


def test_write_truncates_longest_field_first(tmp_path):
    path = str(tmp_path / "crash.json")
    service = CrashLogService(path=path, max_bytes=200)

    service.write(
        "unhandled_exception", context="mqtt_connect", error="short", trace="y" * 5000
    )

    entry = service.read()
    assert entry["error"] == "short"
    assert entry["trace"].endswith("...[truncated]")


def test_write_best_effort_when_max_bytes_too_small_to_shrink_into(tmp_path):
    path = str(tmp_path / "crash.json")
    service = CrashLogService(path=path, max_bytes=10)

    service.write("unhandled_exception", context="mqtt_connect")

    entry = service.read()
    assert entry is not None
    assert "ts" in entry


def test_write_under_max_bytes_is_not_truncated(tmp_path):
    service = make_service(tmp_path)

    service.write("unhandled_exception", context="mqtt_connect", trace="short trace")

    entry = service.read()
    assert entry["trace"] == "short trace"
