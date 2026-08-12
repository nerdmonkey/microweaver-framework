import ntptime


class NtpSyncService:
    def __init__(self, server="pool.ntp.org", timeout_seconds=5):
        self.server = server
        self.timeout_seconds = timeout_seconds

    def sync(self):
        ntptime.host = self.server
        if hasattr(ntptime, "timeout"):
            ntptime.timeout = self.timeout_seconds
        ntptime.settime()
