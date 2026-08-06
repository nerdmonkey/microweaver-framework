from app.services.safe_mode import SafeModeService


def test_run_prints_message_and_sleeps_forever(mocker, capsys):
    sleep_mock = mocker.patch(
        "time.sleep", side_effect=[None, None, RuntimeError("stop test")]
    )
    service = SafeModeService(sleep_seconds=3)

    try:
        service.run()
    except RuntimeError:
        pass

    assert sleep_mock.call_args_list == [
        mocker.call(3),
        mocker.call(3),
        mocker.call(3),
    ]
    out = capsys.readouterr().out
    assert "SAFE MODE" in out


def test_run_uses_default_sleep_seconds(mocker):
    sleep_mock = mocker.patch("time.sleep", side_effect=RuntimeError("stop test"))
    service = SafeModeService()

    try:
        service.run()
    except RuntimeError:
        pass

    sleep_mock.assert_called_once_with(5)
