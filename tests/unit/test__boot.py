from unittest.mock import MagicMock

import _boot


def test_run_bootstrap_imports_main_and_starts(mocker):
    gc_mock = mocker.patch("_boot.gc")
    reset_service_cls = mocker.patch("_boot.ResetService")
    mock_main = MagicMock()
    mocker.patch.dict("sys.modules", {"main": mock_main})

    _boot.run_bootstrap()

    assert gc_mock.collect.call_count == 2
    reset_service_cls.return_value.read.assert_called_once_with()
    mock_main.start.assert_called_once_with()
