class BaseAdapter:
    """Contract every sensor/actuator/indicator adapter subclasses.

    Required surface (frozen — do not rename/remove, only extend in subclasses):
      - `available` property: reports whether the underlying hardware
        initialized successfully. Set `_available` in the subclass once
        setup succeeds.
      - `setup()` lifecycle hook: called once by the owning service before
        first use. Do pin/bus configuration here, not in `__init__`, so
        construction stays cheap and side-effect-free.
      - `deinit()` lifecycle hook: called on teardown (safe mode, restart)
        to release pins/bus handles. Must be safe to call even if `setup()`
        never ran or already failed.
    """

    _available = False

    @property
    def available(self):
        return self._available

    def setup(self):
        pass

    def deinit(self):
        pass
