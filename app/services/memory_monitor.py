import gc

from machine import reset


class MemoryMonitorService:
    def __init__(self, threshold_bytes=10000, action="log"):
        self.threshold_bytes = threshold_bytes
        self.action = action

    def free_bytes(self):
        return gc.mem_free()

    def check(self):
        free = self.free_bytes()
        if free >= self.threshold_bytes:
            return False

        if self.action == "restart":
            print(
                "MEMORY: free heap",
                free,
                "bytes below threshold",
                self.threshold_bytes,
                "- restarting",
            )
            reset()
        elif self.action == "warn":
            print(
                "MEMORY WARNING: free heap",
                free,
                "bytes below threshold",
                self.threshold_bytes,
            )
        else:
            print(
                "MEMORY: free heap",
                free,
                "bytes below threshold",
                self.threshold_bytes,
            )

        return True
