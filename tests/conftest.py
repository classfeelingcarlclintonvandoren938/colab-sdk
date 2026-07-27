"""Shared pytest fixtures for Colab Client tests."""

import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

import pytest


@pytest.fixture(autouse=True)
def _mock_win32_platform() -> Generator[None, None, None]:
    """Mock ``sys.platform`` to ``\"linux\"`` for session tests.

    ``ColabSession.__init__`` raises ``SessionError`` on native Windows
    (``google-colab-cli`` requires WSL2).  This fixture overrides the
    platform so the session tests can verify CLI behavior without hitting
    the Windows guard.
    """
    with _patch_platform("linux"):
        yield


@contextmanager
def _patch_platform(target: str) -> Generator[None, None, None]:
    """Context manager that monkey-patches ``sys.platform``."""
    from unittest.mock import patch

    with patch("colab._session.sys.platform", target):
        yield


@pytest.fixture
def tmp_project() -> Generator[Path, None, None]:
    """Create a temporary project directory with a standard structure.

    The project has the following layout::

        <tmp>/
        ├── app.py              # entry point with ``train()``
        ├── utils/
        │   ├── __init__.py
        │   └── helper.py
        └── training/
            ├── __init__.py
            └── trainer.py
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        # --- app.py ---
        (root / "app.py").write_text(
            "from training.trainer import train\n"
            "from utils.helper import HELP\n"
            "import numpy\n"
            "\n"
            "\n"
            "def run():\n"
            "    return train(epochs=10)\n"
        )

        # --- utils/__init__.py ---
        (root / "utils").mkdir()
        (root / "utils" / "__init__.py").write_text("")

        # --- utils/helper.py ---
        (root / "utils" / "helper.py").write_text(
            "HELP = 42\n"
        )

        # --- training/__init__.py ---
        (root / "training").mkdir()
        (root / "training" / "__init__.py").write_text("")

        # --- training/trainer.py ---
        (root / "training" / "trainer.py").write_text(
            "import torch\n"
            "from utils.helper import HELP\n"
            "\n"
            "\n"
            "def train(epochs=10):\n"
            '    return {"done": True, "epochs": epochs, "help": HELP}\n'
        )

        yield root
