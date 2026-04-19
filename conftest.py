"""Mock the ComfyUI 'server' module so the root __init__.py can be imported by pytest."""

import sys
from unittest.mock import MagicMock

sys.modules["server"] = MagicMock()
