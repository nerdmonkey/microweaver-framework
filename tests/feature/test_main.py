import importlib


def test_importing_main_has_no_side_effects():
    module = importlib.import_module("main")
    assert hasattr(module, "start")
