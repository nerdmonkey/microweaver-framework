import time

import network


class WiFiService:
    def __init__(self, ssid, password, connect_timeout_seconds=20):
        self.ssid = ssid
        self.password = password
        self.connect_timeout_seconds = connect_timeout_seconds
        self.wlan = network.WLAN(network.STA_IF)

    def connect(self):
        if self.wlan.isconnected():
            return True

        self.wlan.active(True)
        print("Connecting to network...")
        self.wlan.connect(self.ssid, self.password)

        deadline = time.time() + self.connect_timeout_seconds
        while not self.wlan.isconnected():
            if time.time() >= deadline:
                print("Failed to connect to network: timed out")
                return False
            time.sleep(1)

        print("Network connected!")
        print("IP Address:", self.wlan.ifconfig()[0])
        return True

    def is_connected(self):
        return self.wlan.isconnected()
