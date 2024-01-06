

class Core:
    def __init__(self, mosquitto):
        self.mosquitto = mosquitto

    def run(self):
        try:
            self.mosquitto.start()

            while True:
                message = input("Enter message to publish or type 'exit' to quit: ")
                if message.lower() == 'exit':
                    break
                self.mosquitto.publish(message)

        except Exception as e:
            print(f"An error occurred: {e}")
        finally:
            self.mosquitto.stop()
