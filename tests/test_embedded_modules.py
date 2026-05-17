"""Tests for embedded_modules — auto-discovery of runtime helpers.

Verifies that the module-level source embedding approach correctly:
  - Strips all import statements from contributing modules
  - Preserves function definitions, constants, and docstrings
  - Produces valid Python when concatenated
  - Includes all expected helper functions
"""

import ast
import unittest


class TestStripImports(unittest.TestCase):
    """Tests for _strip_imports — removes import lines, keeps everything else."""

    def setUp(self):
        from comfyui_to_python.generator.embedded_modules import _strip_imports

        self._strip_imports = _strip_imports

    def test_removes_simple_imports(self):
        source = "import os\nimport sys\n\ndef foo(): pass"
        result = self._strip_imports(source)
        self.assertNotIn("import os", result)
        self.assertNotIn("import sys", result)
        self.assertIn("def foo(): pass", result)

    def test_removes_from_imports(self):
        source = "from typing import Any\nfrom .runtime import x\n\ndef bar(): pass"
        result = self._strip_imports(source)
        self.assertNotIn("from typing", result)
        self.assertNotIn("from .runtime", result)
        self.assertIn("def bar(): pass", result)

    def test_removes_future_imports(self):
        source = "from __future__ import annotations\n\ndef baz(): pass"
        result = self._strip_imports(source)
        self.assertNotIn("__future__", result)
        self.assertIn("def baz(): pass", result)

    def test_preserves_docstrings(self):
        source = (
            '"""Module docstring."""\n'
            "import os\n\n"
            "def foo():\n"
            '    """Function docstring."""\n'
            "    pass"
        )
        result = self._strip_imports(source)
        self.assertIn("Module docstring", result)
        self.assertIn("Function docstring", result)

    def test_preserves_constants(self):
        source = "import os\n\nCONST = 42\n"
        result = self._strip_imports(source)
        self.assertIn("CONST = 42", result)
        self.assertNotIn("import os", result)

    def test_removes_multiline_imports(self):
        source = (
            "from typing import (\n    Any,\n    List,\n    Dict,\n)\ndef foo(): pass\n"
        )
        result = self._strip_imports(source)
        self.assertNotIn("from typing", result)
        self.assertNotIn("Any", result) or "Any" not in result.split("def")[0]
        self.assertIn("def foo(): pass", result)


class TestGetEmbeddedHelpers(unittest.TestCase):
    """Tests for get_embedded_helpers — produces valid, complete embedded code."""

    def setUp(self):
        from comfyui_to_python.generator.embedded_modules import (
            get_embedded_helpers,
            list_embedded_names,
        )

        self.get_embedded_helpers = get_embedded_helpers
        self.list_embedded_names = list_embedded_names

    def test_returns_string(self):
        result = self.get_embedded_helpers()
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 1000)

    def test_is_valid_python(self):
        result = self.get_embedded_helpers()
        # Should parse without syntax errors (may have NameErrors at runtime
        # for non-builtin references, but should be syntactically valid)
        ast.parse(result)

    def test_no_import_statements(self):
        result = self.get_embedded_helpers()
        tree = ast.parse(result)
        top_level_imports = [
            node
            for node in ast.iter_child_nodes(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
        ]
        self.assertEqual(
            top_level_imports,
            [],
            f"Found {len(top_level_imports)} top-level import(s) in embedded block",
        )

    def test_contains_key_functions(self):
        result = self.get_embedded_helpers()
        required = [
            "_apply_device_settings",
            "_apply_directory_overrides",
            "_bootstrap_import",
            "_discover_comfyui_cli_options",
            "_filter_comfyui_args",
            "_load_module",
            "_load_module_temp",
            "add_extra_model_paths",
            "bootstrap_comfyui_runtime",
            "cleanup_comfyui_runtime",
            "import_custom_nodes",
        ]
        for name in required:
            self.assertIn(
                f"def {name}(",
                result,
                f"Missing function: {name}",
            )

    def test_no_relative_imports(self):
        import re

        result = self.get_embedded_helpers()
        matches = re.findall(r"^from\s+\.\s*", result, re.MULTILINE)
        self.assertEqual(
            matches,
            [],
            f"Found {len(matches)} relative imports in embedded block",
        )

    def test_names_match_definitions(self):
        names = self.list_embedded_names()
        result = self.get_embedded_helpers()
        for name in names:
            self.assertIn(
                f"def {name}(",
                result,
                f"list_embedded_names includes '{name}' but definition not found",
            )


class TestListEmbeddedNames(unittest.TestCase):
    """Tests for list_embedded_names — discovers all top-level definitions."""

    def test_includes_private_functions(self):
        from comfyui_to_python.generator.embedded_modules import list_embedded_names

        names = list_embedded_names()
        private_funcs = {"_bootstrap_import", "_load_module", "_filter_comfyui_args"}
        for name in private_funcs:
            self.assertIn(name, names)

    def test_includes_public_functions(self):
        from comfyui_to_python.generator.embedded_modules import list_embedded_names

        names = list_embedded_names()
        public_funcs = {
            "bootstrap_comfyui_runtime",
            "cleanup_comfyui_runtime",
            "import_custom_nodes",
            "add_extra_model_paths",
        }
        for name in public_funcs:
            self.assertIn(name, names)

    def test_excludes_log(self):
        from comfyui_to_python.generator.embedded_modules import list_embedded_names

        names = list_embedded_names()
        # 'log' is the logger instance — not useful to embed
        self.assertNotIn("log", names)

    def test_surface_matches_approved_manifest(self):
        from comfyui_to_python.generator.embedded_modules import (
            verify_embedded_surface_matches_manifest,
        )

        differences = verify_embedded_surface_matches_manifest()

        self.assertEqual(differences, [])


class TestVerifyNoMissingCrossCalls(unittest.TestCase):
    """Tests for verify_no_missing_cross_calls — catches missing dependencies."""

    def test_returns_empty_list(self):
        from comfyui_to_python.generator.embedded_modules import (
            verify_no_missing_cross_calls,
        )

        unresolved = verify_no_missing_cross_calls()
        self.assertEqual(unresolved, [])


if __name__ == "__main__":
    unittest.main()
