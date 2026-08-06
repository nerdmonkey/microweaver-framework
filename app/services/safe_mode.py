import time


class SafeModeService:
    def __init__(self, sleep_seconds=5):
        self.sleep_seconds = sleep_seconds

    def run(self):
        print("SAFE MODE: user services disabled, awaiting recovery/reflash")
        while True:
            time.sleep(self.sleep_seconds)
