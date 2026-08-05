from app.adapters.base import BaseAdapter


def test_available_defaults_to_false():
    adapter = BaseAdapter()
    assert adapter.available is False


def test_available_reflects_subclass_state():
    class FakeAdapter(BaseAdapter):
        _available = True

    assert FakeAdapter().available is True


def test_deinit_is_a_noop():
    adapter = BaseAdapter()
    assert adapter.deinit() is None
