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


def test_run_reconnects_through_repeated_drops(mocker):
    mocker.patch("app.services.subscribe.WiFiService")
    mock_connection_cls = mocker.patch("app.services.subscribe.MqttConnection")
    mock_connection = mock_connection_cls.return_value
    client_a, client_b = MagicMock(), MagicMock()
    client_a.wait_msg.side_effect = OSError("dropped")
    client_b.wait_msg.side_effect = ConnectionResetError("dropped again")
    mock_connection.connect.side_effect = [
        client_a,
        client_b,
        RuntimeError("stop test"),
    ]

    service = SubscribeService()

    with pytest.raises(RuntimeError, match="stop test"):
        service.run()

    assert mock_connection.connect.call_count == 3
    assert mock_connection.disconnect.call_count == 2
    client_a.subscribe.assert_called_once_with(service.topic)
    client_b.subscribe.assert_called_once_with(service.topic)


def test_on_message_logs_received_payload(capsys):
    service = SubscribeService()

    service.on_message(b"sensors/temp", b"21.5")

    out = capsys.readouterr().out
    assert "sensors/temp" in out
    assert "21.5" in out
