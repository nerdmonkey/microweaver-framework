

def handle(msg):
    if msg.topic == "command/control/motor":
        print(msg.payload.decode())
        print(f"Command Control Motor")

    if msg.topic == "command/control/light":
        print(msg.payload.decode())
        print(f"Command to turn light on and off")

    return None
