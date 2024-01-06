from app.core import Core
from app.services.mosquitto import Mosquitto
from environment import APP_ENVIRONMENT, MQTT_BROKER, MQTT_CLIENT_ID, MQTT_PORT, MQTT_TOPIC_PUB, MQTT_TOPIC_SUB, MQTT_USERNAME, MQTT_PASSWORD

# Ensure that MQTT_USERNAME and MQTT_PASSWORD are used appropriately in Mosquitto class

mosquitto = Mosquitto(MQTT_CLIENT_ID, MQTT_BROKER, MQTT_PORT, MQTT_TOPIC_SUB, MQTT_TOPIC_PUB)
core = Core(mosquitto)
core.run()
