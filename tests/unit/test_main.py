from unittest.mock import patch

import pytest


@pytest.fixture
def mock_publish(mocker):
    mocker.patch("app.services.publish.PublishService")


@pytest.fixture
def mock_subscribe(mocker):
    mocker.patch("pp.services.publish.SubscribeService")


# def test_main():
#     with patch("app.core.Core") as MockCore:
#         with patch("app.services.mosquitto.Mosquitto") as MockMosquitto:
#             import main

#             assert MockCore.called is True
#             assert MockMosquitto.called is True
#             assert MockCore.return_value.run.called is True
#             assert main.core == MockCore.return_value
