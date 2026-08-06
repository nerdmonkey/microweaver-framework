import main


def test_start_wires_and_runs_publish_service(mocker):
    mock_publish_cls = mocker.patch("main.PublishService")
    mock_instance = mock_publish_cls.return_value

    main.start()

    mock_publish_cls.assert_called_once_with()
    mock_instance.run.assert_called_once_with()


def test_start_safe_mode_wires_and_runs_safe_mode_service(mocker):
    mocker.patch("main.setting.SAFE_MODE_SLEEP_SECONDS", 7)
    mock_safe_mode_cls = mocker.patch("main.SafeModeService")
    mock_instance = mock_safe_mode_cls.return_value

    main.start_safe_mode()

    mock_safe_mode_cls.assert_called_once_with(7)
    mock_instance.run.assert_called_once_with()
