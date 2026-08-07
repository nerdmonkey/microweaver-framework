class ServiceRegistry:
    """Boot-lifecycle contract for core services.

    Services register an optional `start`/`stop` callable under a name.
    `start_all()` runs them in registration order; `stop_all()` runs them
    in reverse order, so the last service started is the first torn down.
    A failing `start` or `stop` is logged and skipped rather than aborting
    the rest of boot/teardown — mirrors the "safe to call even if setup
    never ran" rule `BaseAdapter.deinit()` follows in `app/adapters/base.py`.
    Pass an `ErrorHandlerService` as `error_handler` to route failures
    through structured logging instead of the default `print`.
    """

    def __init__(self, error_handler=None):
        self._entries = []
        self.error_handler = error_handler

    def register(self, name, start=None, stop=None):
        self._entries.append((name, start, stop))
        return self

    def register_adapter(self, name, adapter):
        """Register a `BaseAdapter` under its `setup`/`deinit` pair.

        Bridges the adapter lifecycle contract (`app/adapters/base.py`)
        onto the `start`/`stop` callables `start_all`/`stop_all` expect,
        so adapters boot and tear down in the same order-guaranteed way
        as `watchdog` and other core services.
        """
        return self.register(name, start=adapter.setup, stop=adapter.deinit)

    def start_all(self):
        for name, start, _stop in self._entries:
            if start:
                self._run_safely("start", name, start)

    def stop_all(self):
        for name, _start, stop in reversed(self._entries):
            if stop:
                self._run_safely("stop", name, stop)

    def _run_safely(self, verb, name, fn):
        if self.error_handler:
            self.error_handler.guard(fn, "service_{}:{}".format(verb, name))
            return
        try:
            fn()
        except Exception as e:
            print("Failed to {} service:".format(verb), name, "-", e)
