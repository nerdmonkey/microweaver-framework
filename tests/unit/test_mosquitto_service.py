import json
from unittest.mock import MagicMock, patch

import pytest

from app.services.mosquitto import Mosquitto
from environment import MQTT_CLIENT_ID


@pytest.fixture(autouse=True)
def mock_umqtt_module():
    with patch.dict("sys.modules", {"umqtt": MagicMock(), "umqtt.simple": MagicMock()}):
        yield


@pytest.fixture
def mock_paho_client(mocker):
    with patch("paho.mqtt.client.Client") as MockClient:
        yield MockClient.return_value


@pytest.fixture
def mock_umqtt_client(mocker):
    with patch("umqtt.simple.MQTTClient") as MockClient:
        yield MockClient.return_value


def test_mosquitto_initialization_device(mock_umqtt_client, monkeypatch):
    monkeypatch.setattr("environment.APP_ENVIRONMENT", "device")
    mosquitto = Mosquitto()
    assert mosquitto.client_id == MQTT_CLIENT_ID


def test_mosquitto_initialization_other(mock_paho_client, monkeypatch):
    monkeypatch.setattr("environment.APP_ENVIRONMENT", "device")
    mosquitto = Mosquitto()
    assert mosquitto.client_id == MQTT_CLIENT_ID


def test_on_connect(mock_paho_client):
    mosquitto = Mosquitto()
    mosquitto.on_connect(mock_paho_client, None, None, 0)
    mock_paho_client.subscribe.assert_called_with(mosquitto.sub_topic)


def test_on_message(mock_paho_client):
    mosquitto = Mosquitto()
    test_message = MagicMock()
    test_message.payload = json.dumps({"test": "data"}).encode()
    test_message.topic = "some/test/topic"
    mosquitto.on_message(mock_paho_client, None, test_message)
