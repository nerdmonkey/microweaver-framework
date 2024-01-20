import time
import json

class Core:
    def __init__(self, mosquitto):
        self.mosquitto = mosquitto

    def run(self):
        try:
            self.mosquitto.start()

            while True:
                message = json.dumps({
                    "temperature": 30,
                    "humidity": 80,
                    "timestamp": time.time(),
                })

                topic = "data/sensor/temperature"

                self.mosquitto.publish(topic, message)
                time.sleep(3)

        except Exception as e:
            print(f"An error occurred: {e}")
        finally:
            self.mosquitto.stop()
