class ServiceRegistry:
    """Boot-lifecycle contract for core services.

    Services register an optional `start`/`stop` callable under a name.
    `start_all()` runs them in registration order; `stop_all()` runs them
    in reverse order, so the last service started is the first torn down.
    A failing `stop` is printed and skipped rather than aborting the rest
    of teardown — mirrors the "safe to call even if setup never ran" rule
    `BaseAdapter.deinit()` follows in `app/adapters/base.py`.
    """

    def __init__(self):
        self._entries = []

    def register(self, name, start=None, stop=None):
        self._entries.append((name, start, stop))
        return self

    def start_all(self):
        for name, start, _stop in self._entries:
            if start:
                start()

    def stop_all(self):
        for name, _start, stop in reversed(self._entries):
            if not stop:
                continue
            try:
                stop()
            except Exception as e:
                print("Failed to stop service:", name, "-", e)
