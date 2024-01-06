from unittest.mock import patch

import pytest


@pytest.fixture
def mock_mosquitto(mocker):
    mocker.patch("app.services.mosquitto.Mosquitto")


@pytest.fixture
def mock_core(mocker):
    mocker.patch("app.core.Core")


def test_main(mock_mosquitto, mock_core):
    with patch("app.core.Core") as MockCore:
        with patch("app.services.mosquitto.Mosquitto") as MockMosquitto:
            # Importing main.py should execute the script
            pass

            # Check if Mosquitto and Core are instantiated
            assert MockMosquitto.called, "Mosquitto should be instantiated"
            assert MockCore.called, "Core should be instantiated"

            # Create an instance to test method calls
            mock_core_instance = MockCore.return_value
            mock_core_instance.run.assert_called_once()
