import pytest

from config.app import Setting


def test_setting_initialization(monkeypatch):
    test_values = {
        "APP_ENVIRONMENT": "test",
        "MQTT_BROKER": "test_broker",
        "MQTT_CLIENT_ID": "test_id",
        "MQTT_PORT": 1884,
        "MQTT_TOPIC_PUB": "test/pub",
        "MQTT_TOPIC_SUB": "test/sub",
        "MQTT_TOPIC_SUB": "test/sub",
        "MQTT_USERNAME": "test_user",
        "MQTT_PASSWORD": "test_pass",
    }

    for key, value in test_values.items():
        monkeypatch.setattr("environment." + key, value)

    setting = Setting()

    assert setting.APP_ENVIRONMENT == test_values["APP_ENVIRONMENT"]
    assert setting.MQTT_BROKER == test_values["MQTT_BROKER"]
    assert setting.MQTT_CLIENT_ID == test_values["MQTT_CLIENT_ID"]
    assert setting.MQTT_PORT == test_values["MQTT_PORT"]
    assert setting.MQTT_TOPIC_PUB == test_values["MQTT_TOPIC_PUB"]
    assert setting.MQTT_TOPIC_SUB == test_values["MQTT_TOPIC_SUB"]
    assert setting.MQTT_USERNAME == test_values["MQTT_USERNAME"]
    assert setting.MQTT_PASSWORD == test_values["MQTT_PASSWORD"]


def test_get_settings_method():
    setting = Setting()
    retrieved_settings = setting.get_settings()
    assert (
        retrieved_settings == setting
    ), "get_settings should return the Setting instance"
