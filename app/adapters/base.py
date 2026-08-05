class BaseAdapter:
    _available = False

    @property
    def available(self):
        return self._available

    def deinit(self):
        pass
