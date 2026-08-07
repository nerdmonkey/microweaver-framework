import time

import network


class WiFiService:
    def __init__(
        self,
        ssid,
        password,
        connect_timeout_seconds=20,
        reconnect_delay_seconds=2,
        max_reconnect_delay_seconds=30,
        watchdog_service=None,
        static_ip=None,
        disable_power_save=False,
    ):
        self.ssid = ssid
        self.password = password
        self.connect_timeout_seconds = connect_timeout_seconds
        self.reconnect_delay_seconds = reconnect_delay_seconds
        self.max_reconnect_delay_seconds = max_reconnect_delay_seconds
        self.watchdog_service = watchdog_service
        self.static_ip = static_ip
        self.disable_power_save = disable_power_save
        self.wlan = network.WLAN(network.STA_IF)

    def _configure_interface(self):
        self.wlan.active(True)
        if self.disable_power_save:
            self.wlan.config(pm=network.WLAN.PM_NONE)
        if self.static_ip:
            self.wlan.ifconfig(self.static_ip)

    def _reset_interface(self):
        try:
            self.wlan.disconnect()
        except Exception:
            pass
        self.wlan.active(False)
        time.sleep(1)
        self._configure_interface()

    def connect(self):
        if self.wlan.isconnected():
            return True

        delay = self.reconnect_delay_seconds
        while True:
            if self.watchdog_service:
                self.watchdog_service.feed()

            self._reset_interface()
            print("Connecting to network...")
            try:
                self.wlan.connect(self.ssid, self.password)
            except OSError as err:
                print("Failed to start WiFi connection:", err)
                time.sleep(delay)
                delay = min(delay * 2, self.max_reconnect_delay_seconds)
                continue

            if self._wait_until_connected():
                print("Network connected!")
                print("IP Address:", self.wlan.ifconfig()[0])
                return True

            print("Failed to connect to network: timed out - retrying in", delay, "s")
            time.sleep(delay)
            delay = min(delay * 2, self.max_reconnect_delay_seconds)

    def _wait_until_connected(self):
        deadline = time.time() + self.connect_timeout_seconds
        while not self.wlan.isconnected():
            if time.time() >= deadline:
                return False
            time.sleep(1)
        return True

    def is_connected(self):
        return self.wlan.isconnected()

    def rssi(self):
        return self.wlan.status("rssi")

    def ensure_connected(self):
        if not self.wlan.isconnected():
            self.connect()
