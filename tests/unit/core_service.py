from unittest.mock import MagicMock

import pytest

from app.core import Core


@pytest.fixture
def mock_mosquitto(mocker):
    mock_mqtt = MagicMock()
    mocker.patch("app.services.mosquitto.Mosquitto", return_value=mock_mqtt)
    return mock_mqtt


def test_core_run(mock_mosquitto, mocker):
    mocker.patch("builtins.input", side_effect=["test message", "exit"])
    core = Core(mock_mosquitto)
    core.run()
    mock_mosquitto.publish.assert_called_with("test message")
    mock_mosquitto.start.assert_called_once()
    mock_mosquitto.stop.assert_called_once()
