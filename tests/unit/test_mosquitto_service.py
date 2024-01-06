import pytest
from unittest.mock import patch
from app.services.mosquitto import Mosquitto  # Adjust this import to your project structure
import environment

@pytest.fixture
def mock_mqtt_client(mocker):
    with patch('paho.mqtt.client.Client') as mock_client:
        yield mock_client

def test_mosquitto_initialization(mock_mqtt_client, monkeypatch):
    # Temporarily set APP_ENVIRONMENT to a value that uses paho.mqtt
    monkeypatch.setattr('environment.APP_ENVIRONMENT', 'not-device')

    Mosquitto("client-id", "localhost", 1883, "sub_topic", "pub_topic")
    assert mock_mqtt_client.called, "The MQTT Client should be instantiated"
