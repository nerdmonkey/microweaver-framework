class ServiceRestartService:
    def __init__(self, restarts=None, max_attempts=3):
        self.restarts = dict(restarts) if restarts else {}
        self.max_attempts = max_attempts
        self.attempts = {}

    def register(self, name, restart):
        self.restarts[name] = restart

    def reconcile(self, status):
        restarted = []

        for name, entry in status.items():
            if entry["healthy"]:
                self.attempts[name] = 0
                continue

            restart = self.restarts.get(name)
            if restart is None:
                continue

            attempts = self.attempts.get(name, 0)
            if attempts >= self.max_attempts:
                continue

            self.attempts[name] = attempts + 1
            try:
                print("Restarting unhealthy service:", name)
                restart()
                restarted.append(name)
            except Exception as e:
                print("Failed to restart service:", name, "-", e)

        return restarted
