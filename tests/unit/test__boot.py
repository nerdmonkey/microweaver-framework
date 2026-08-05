from unittest.mock import MagicMock

import _boot


def test_run_bootstrap_imports_main_and_starts(mocker):
    gc_mock = mocker.patch("_boot.gc")
    mock_main = MagicMock()
    mocker.patch.dict("sys.modules", {"main": mock_main})

    _boot.run_bootstrap()

    assert gc_mock.collect.call_count == 2
    mock_main.start.assert_called_once_with()
