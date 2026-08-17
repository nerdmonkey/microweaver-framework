import time

import ntptime


class NtpService:
    def __init__(self, host="pool.ntp.org", sync_attempts=3, retry_delay_seconds=1):
        self.host = host
        self.sync_attempts = sync_attempts
        self.retry_delay_seconds = retry_delay_seconds

    def sync(self):
        ntptime.host = self.host
        for attempt in range(1, self.sync_attempts + 1):
            try:
                ntptime.settime()
                print("NTP time synced from", self.host)
                return True
            except Exception as e:
                print("NTP sync failed (attempt", attempt, "):", e)
                if attempt < self.sync_attempts:
                    time.sleep(self.retry_delay_seconds)
        return False
