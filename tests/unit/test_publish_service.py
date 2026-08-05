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
