import sys
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def clean_boot_module():
    sys.modules.pop("boot", None)
    sys.modules.pop("_boot", None)
    yield
    sys.modules.pop("boot", None)
    sys.modules.pop("_boot", None)


def test_boot_runs_bootstrap_successfully(clean_boot_module):
    mock_run_bootstrap = MagicMock()
    sys.modules["_boot"] = MagicMock(run_bootstrap=mock_run_bootstrap)

    import boot  # noqa: F401

    mock_run_bootstrap.assert_called_once_with()


def test_boot_logs_and_reraises_on_exception(clean_boot_module):
    mock_run_bootstrap = MagicMock(side_effect=RuntimeError("boom"))
    sys.modules["_boot"] = MagicMock(run_bootstrap=mock_run_bootstrap)

    with pytest.raises(RuntimeError, match="boom"):
        import boot  # noqa: F401


def test_boot_leaves_repl_when_bootstrap_function_missing(clean_boot_module, capsys):
    sys.modules["_boot"] = MagicMock(spec=[])

    import boot  # noqa: F401

    captured = capsys.readouterr()
    assert "missing run_bootstrap" in captured.out
