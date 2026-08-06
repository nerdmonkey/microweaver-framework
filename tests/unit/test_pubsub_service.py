from unittest.mock import MagicMock

from app.services.pubsub import PubSubService


def make_pubsub_service(connected_client=None):
    connection = MagicMock()
    connection.connect.return_value = connected_client
    return PubSubService(connection), connection


def test_connect_stores_and_returns_client():
    mock_client = MagicMock()
    service, connection = make_pubsub_service(mock_client)

    result = service.connect()

    assert result is mock_client
    assert service.client is mock_client
    connection.connect.assert_called_once_with()


def test_disconnect_clears_client():
    mock_client = MagicMock()
    service, connection = make_pubsub_service(mock_client)
    service.connect()

    service.disconnect()

    connection.disconnect.assert_called_once_with()
    assert service.client is None


def test_publish_sends_encoded_message():
    mock_client = MagicMock()
    service, _ = make_pubsub_service(mock_client)
    service.connect()

    service.publish("topic/a", "hi")

    mock_client.publish.assert_called_once_with("topic/a", b"hi")


def test_publish_without_client_is_noop():
    service, _ = make_pubsub_service()

    service.publish("topic/a", "hi")


def test_publish_survives_exception():
    mock_client = MagicMock()
    mock_client.publish.side_effect = OSError("broker unreachable")
    service, _ = make_pubsub_service(mock_client)
    service.connect()

    service.publish("topic/a", "hi")

    mock_client.publish.assert_called_once_with("topic/a", b"hi")


def test_subscribe_sets_callback_and_subscribes():
    mock_client = MagicMock()
    service, _ = make_pubsub_service(mock_client)
    service.connect()
    callback = MagicMock()

    service.subscribe("topic/b", callback)

    mock_client.set_callback.assert_called_once_with(callback)
    mock_client.subscribe.assert_called_once_with("topic/b")


def test_subscribe_without_client_is_noop():
    service, _ = make_pubsub_service()
    callback = MagicMock()

    service.subscribe("topic/b", callback)


def test_check_messages_polls_client():
    mock_client = MagicMock()
    service, _ = make_pubsub_service(mock_client)
    service.connect()

    service.check_messages()

    mock_client.check_msg.assert_called_once_with()


def test_check_messages_without_client_is_noop():
    service, _ = make_pubsub_service()

    service.check_messages()
