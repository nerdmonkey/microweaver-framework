import os
import time

import machine


class FactoryResetService:
    def __init__(
        self,
        pin=-1,
        hold_seconds=3,
        sentinel_path="reprovision.flag",
        setting=None,
    ):
        self.pin = pin
        self.hold_seconds = hold_seconds
        self.sentinel_path = sentinel_path
        self.setting = setting

    def should_trigger(self):
        if self._sentinel_exists():
            return True
        return self._button_held()

    def clear_credentials(self):
        if self.setting:
            self.setting.save(
                wifi_ssid="",
                wifi_password="",  # nosec B106 - clearing credential, not setting one
                mqtt_username="",
                mqtt_password="",  # nosec B106 - clearing credential, not setting one
                claim_code="",
                device_id="",
                device_cert="",
                device_key="",
            )
        self._clear_sentinel()
        print("Factory reset: credentials cleared, re-entering provisioning")

    def _sentinel_exists(self):
        try:
            with open(self.sentinel_path, "r"):
                return True
        except OSError:
            return False

    def _clear_sentinel(self):
        try:
            os.remove(self.sentinel_path)
        except OSError:
            pass

    def _button_held(self):
        if self.pin is None or self.pin < 0:
            return False

        button = machine.Pin(self.pin, machine.Pin.IN, machine.Pin.PULL_UP)
        if button.value() != 0:
            return False

        print("Factory reset button held, hold for", self.hold_seconds, "s to confirm")
        deadline = time.time() + self.hold_seconds
        while time.time() < deadline:
            if button.value() != 0:
                return False
            time.sleep(1)
        return True
