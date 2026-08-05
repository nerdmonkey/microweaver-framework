from unittest.mock import MagicMock

import pytest

from app.services.subscribe import SubscribeService


def test_run_reconnects_after_connection_loss(mocker):
    mocker.patch("app.services.subscribe.WiFiService")
    mock_connection_cls = mocker.patch("app.services.subscribe.MqttConnection")
    mock_connection = mock_connection_cls.return_value
    mock_client = MagicMock()
    mock_client.wait_msg.side_effect = OSError("dropped")
    mock_connection.connect.side_effect = [mock_client, RuntimeError("stop test")]

    service = SubscribeService()

    with pytest.raises(RuntimeError, match="stop test"):
        service.run()

    mock_client.set_callback.assert_called_once_with(service.on_message)
    mock_client.subscribe.assert_called_once_with(service.topic)
    assert mock_connection.disconnect.call_count == 1
