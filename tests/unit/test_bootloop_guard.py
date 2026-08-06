from app.services.bootloop import BootLoopGuard


def make_guard(tmp_path, max_attempts=3, enabled=True):
    path = str(tmp_path / "boot_state.json")
    return BootLoopGuard(path=path, max_attempts=max_attempts, enabled=enabled)


def test_check_returns_false_while_under_threshold(tmp_path):
    guard = make_guard(tmp_path, max_attempts=3)

    assert guard.check() is False
    assert guard.check() is False
    assert guard.check() is False
    assert guard.attempts == 3


def test_check_returns_true_once_threshold_exceeded(tmp_path):
    guard = make_guard(tmp_path, max_attempts=2)

    assert guard.check() is False
    assert guard.check() is False
    assert guard.check() is True
    assert guard.attempts == 3


def test_check_persists_attempts_across_instances(tmp_path):
    path = str(tmp_path / "boot_state.json")

    BootLoopGuard(path=path, max_attempts=5).check()
    BootLoopGuard(path=path, max_attempts=5).check()
    third = BootLoopGuard(path=path, max_attempts=5)

    assert third.check() is False
    assert third.attempts == 3


def test_confirm_resets_attempts(tmp_path):
    path = str(tmp_path / "boot_state.json")

    BootLoopGuard(path=path, max_attempts=2).check()
    BootLoopGuard(path=path, max_attempts=2).check()
    BootLoopGuard(path=path, max_attempts=2).confirm()

    guard = BootLoopGuard(path=path, max_attempts=2)
    assert guard.check() is False
    assert guard.attempts == 1


def test_check_is_noop_when_disabled(tmp_path):
    guard = make_guard(tmp_path, max_attempts=1, enabled=False)

    assert guard.check() is False
    assert guard.check() is False
    assert guard.attempts == 0


def test_confirm_is_noop_when_disabled(tmp_path):
    path = str(tmp_path / "boot_state.json")
    BootLoopGuard(path=path, max_attempts=1).check()

    guard = BootLoopGuard(path=path, max_attempts=1, enabled=False)
    guard.confirm()

    reenabled = BootLoopGuard(path=path, max_attempts=1)
    assert reenabled.check() is True


def test_read_falls_back_to_zero_when_state_file_missing(tmp_path):
    guard = make_guard(tmp_path, max_attempts=5)

    assert guard.check() is False
    assert guard.attempts == 1


def test_write_failure_is_printed_not_raised(tmp_path, capsys):
    unwritable_dir = tmp_path / "missing_dir" / "boot_state.json"
    guard = BootLoopGuard(path=str(unwritable_dir), max_attempts=5)

    result = guard.check()

    assert result is False
    out = capsys.readouterr().out
    assert "Failed to persist boot-loop state" in out
