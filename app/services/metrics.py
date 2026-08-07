import time


class MetricsService:
    def __init__(self):
        self.start_time = time.time()
        self.messages_published = 0
        self.messages_received = 0
        self.errors = 0

    def record_publish(self):
        self.messages_published += 1

    def record_message(self):
        self.messages_received += 1

    def record_error(self):
        self.errors += 1

    def uptime_seconds(self):
        return time.time() - self.start_time

    def snapshot(self):
        return {
            "uptime_seconds": self.uptime_seconds(),
            "messages_published": self.messages_published,
            "messages_received": self.messages_received,
            "errors": self.errors,
        }
