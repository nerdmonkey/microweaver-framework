import network
import time


class WiFiService:
    def __init__(self, ssid, password):
        self.ssid = ssid
        self.password = password
        self.wlan = network.WLAN(network.STA_IF)

    def connect(self):
        if not self.wlan.isconnected():
            self.wlan.active(True)
            print('Connecting to network...')
            self.wlan.connect(self.ssid, self.password)
            while not self.wlan.isconnected():
                time.sleep(1)  # Sleep to prevent blocking the code too tightly
            print('Network connected!')
            print('IP Address:', self.wlan.ifconfig()[0])

    def is_connected(self):
        return self.wlan.isconnected()
