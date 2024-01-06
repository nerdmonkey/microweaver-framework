from app.core import Core
from app.services.mosquitto import Mosquitto
from environment import (
    MQTT_BROKER,
    MQTT_CLIENT_ID,
    MQTT_PORT,
    MQTT_TOPIC_PUB,
    MQTT_TOPIC_SUB,
)

mosquitto = Mosquitto(
    MQTT_CLIENT_ID, MQTT_BROKER, MQTT_PORT, MQTT_TOPIC_SUB, MQTT_TOPIC_PUB
)
core = Core(mosquitto)
core.run()
