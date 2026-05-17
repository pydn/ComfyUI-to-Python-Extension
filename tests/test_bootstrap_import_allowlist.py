"""Tests for _bootstrap_import allowlist enforcement.

Ensures the allowlist guard in _bootstrap_import cannot be bypassed,
protecting against arbitrary module loading attacks via COMFYUI_PATH.
Must survive all refactoring of module_loader.py.
"""

import unittest

from comfyui_to_python.runtime.module_loader import _bootstrap_import


class TestBootstrapImportAllowlist(unittest.TestCase):
    """_bootstrap_import() must block modules outside allowed prefixes."""

    def test_blocks_unallowed_module_simple(self):
        """Simple unallowed module name is blocked with ValueError."""
        with self.assertRaises(ValueError) as ctx:
            _bootstrap_import("os")
        self.assertIn("'os'", str(ctx.exception))

    def test_blocks_unallowed_module_dotted(self):
        """Dotted unallowed module name is blocked with ValueError."""
        with self.assertRaises(ValueError) as ctx:
            _bootstrap_import("subprocess.popen")
        self.assertIn("'subprocess.popen'", str(ctx.exception))

    def test_blocks_unallowed_module_nested(self):
        """Deeply nested unallowed module name is blocked with ValueError."""
        with self.assertRaises(ValueError) as ctx:
            _bootstrap_import("ctypes.windll.kernel32")
        self.assertIn("'ctypes.windll.kernel32'", str(ctx.exception))

    def test_allows_comfy_prefix(self):
        """Module starting with allowed 'comfy' prefix is not blocked by allowlist."""
        # Will fail with ModuleNotFoundError if comfy isn't available, but should
        # NOT fail with ValueError (which means allowlist blocked it)
        try:
            _bootstrap_import("comfy.nonexistent_module_xyz")
        except ValueError as exc:
            self.fail(f"Allowlist incorrectly blocked 'comfy' prefix: {exc}")
        except ModuleNotFoundError:
            pass  # Expected — module doesn't exist, but allowlist passed

    def test_allows_folder_paths_prefix(self):
        """Module starting with allowed 'folder_paths' prefix is not blocked."""
        try:
            _bootstrap_import("folder_paths.nonexistent_xyz")
        except ValueError as exc:
            self.fail(f"Allowlist incorrectly blocked 'folder_paths' prefix: {exc}")
        except ModuleNotFoundError:
            pass  # Expected — module doesn't exist, but allowlist passed

    def test_allows_execution_prefix(self):
        """Module starting with allowed 'execution' prefix is not blocked."""
        try:
            _bootstrap_import("execution.nonexistent_xyz")
        except ValueError as exc:
            self.fail(f"Allowlist incorrectly blocked 'execution' prefix: {exc}")
        except ModuleNotFoundError:
            pass  # Expected — module doesn't exist, but allowlist passed

    def test_allowlist_list_in_exception(self):
        """Error message includes the allowed prefixes for debugging."""
        with self.assertRaises(ValueError) as ctx:
            _bootstrap_import("os")
        error_msg = str(ctx.exception)
        self.assertIn("comfy", error_msg)
        self.assertIn("folder_paths", error_msg)
