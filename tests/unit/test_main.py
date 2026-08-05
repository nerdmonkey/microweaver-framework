import main


def test_start_wires_and_runs_publish_service(mocker):
    mock_publish_cls = mocker.patch("main.PublishService")
    mock_instance = mock_publish_cls.return_value

    main.start()

    mock_publish_cls.assert_called_once_with()
    mock_instance.run.assert_called_once_with()
