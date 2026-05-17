"""Tests for node_runtime bootstrap state invariants."""

import sys
import tempfile
import unittest
from unittest.mock import patch

from comfyui_to_python.node_runtime import bootstrap_comfyui_runtime


class BootstrapStateInvariantTest(unittest.TestCase):
    def test_bootstrap_restores_argv_when_bootstrap_import_fails(self):
        original_argv = ["generated.py", "--internal-export", "--cpu"]
        filtered_argv = ["generated.py", "--cpu"]
        previous_argv = sys.argv
        sys.argv = list(original_argv)
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                with (
                    patch(
                        "comfyui_to_python.node_runtime.add_comfyui_directory_to_sys_path"
                    ),
                    patch(
                        "comfyui_to_python.node_runtime.get_comfyui_path",
                        return_value=tmpdir,
                    ),
                    patch(
                        "comfyui_to_python.node_runtime._filter_comfyui_args",
                        return_value=filtered_argv,
                    ),
                    patch(
                        "comfyui_to_python.node_runtime._bootstrap_import",
                        side_effect=RuntimeError("boom"),
                    ),
                ):
                    with self.assertRaises(RuntimeError):
                        bootstrap_comfyui_runtime()

            self.assertEqual(sys.argv, original_argv)
        finally:
            sys.argv = previous_argv


if __name__ == "__main__":
    unittest.main()
