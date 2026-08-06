from unittest.mock import MagicMock

import pytest

from app.services.publish import PublishService


def test_run_reconnects_after_connection_loss(mocker):
    mocker.patch("app.services.publish.WiFiService")
    mock_connection_cls = mocker.patch("app.services.publish.MqttConnection")
    mock_connection = mock_connection_cls.return_value
    mock_client = MagicMock()
    mock_connection.connect.side_effect = [mock_client, RuntimeError("stop test")]
    mocker.patch("time.sleep", side_effect=ConnectionResetError("dropped"))

    service = PublishService()

    with pytest.raises(RuntimeError, match="stop test"):
        service.run(message="hi")

    assert mock_connection.connect.call_count == 2
    assert mock_connection.disconnect.call_count == 1
    mock_client.publish.assert_called_once_with(service.topic, b"hi")


def test_run_reconnects_through_repeated_drops(mocker):
    mocker.patch("app.services.publish.WiFiService")
    mock_connection_cls = mocker.patch("app.services.publish.MqttConnection")
    mock_connection = mock_connection_cls.return_value
    client_a, client_b = MagicMock(), MagicMock()
    mock_connection.connect.side_effect = [
        client_a,
        client_b,
        RuntimeError("stop test"),
    ]
    mocker.patch(
        "time.sleep",
        side_effect=[ConnectionResetError("dropped"), OSError("dropped again")],
    )

    service = PublishService()

    with pytest.raises(RuntimeError, match="stop test"):
        service.run(message="hi")

    assert mock_connection.connect.call_count == 3
    assert mock_connection.disconnect.call_count == 2
    client_a.publish.assert_called_once_with(service.topic, b"hi")
    client_b.publish.assert_called_once_with(service.topic, b"hi")


def test_publish_message_survives_publish_exception():
    service = PublishService()
    service.client = MagicMock()
    service.client.publish.side_effect = OSError("broker unreachable")

    service.publish_message("hi")

    service.client.publish.assert_called_once_with(service.topic, b"hi")


def test_publish_message_without_client_is_noop():
    service = PublishService()
    service.client = None

    service.publish_message("hi")
