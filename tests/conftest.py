"""Pytest configuration to handle the ComfyUI extension __init__.py at repo root."""

import sys
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _setup_test_path():
    """Ensure the package is importable during tests."""
    # Add the repo root to sys.path so `from comfyui_to_python import ...` works
    repo_root = Path(__file__).parent.parent.resolve()
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    yield
