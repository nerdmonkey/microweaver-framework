from unittest.mock import patch

import pytest


@pytest.fixture
def mock_mosquitto(mocker):
    mocker.patch("app.services.mosquitto.Mosquitto")


@pytest.fixture
def mock_core(mocker):
    mocker.patch("app.core.Core")


def test_main():
    with patch("app.core.Core") as MockCore:
        with patch("app.services.mosquitto.Mosquitto") as MockMosquitto:
            import main

            assert MockCore.called is True
            assert MockMosquitto.called is True
            assert MockCore.return_value.run.called is True
            assert main.core == MockCore.return_value
