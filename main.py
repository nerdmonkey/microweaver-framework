from app.services.mosquitto import MosquittoService

mqtt_client = MosquittoService()
mqtt_client.run()
