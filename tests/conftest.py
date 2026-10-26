from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# Isolate the SQLite workspace for the whole test session.
_TEST_WORKSPACE = tempfile.mkdtemp(prefix="audiolab_test_")
os.environ.setdefault("AUDIOLAB_WORKSPACE", _TEST_WORKSPACE)
os.environ.setdefault("AUDIOLAB_FAKE", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def workspace() -> Path:
    return Path(os.environ["AUDIOLAB_WORKSPACE"])
