from app.core import Core
from app.services.mosquitto import Mosquitto

mosquitto = Mosquitto()
core = Core(mosquitto)
core.run()
