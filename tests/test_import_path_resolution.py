"""Tests for hardened import path resolution and importlib isolation layer.

Covers Approach B from docs/specs/harden-import-path-resolution.html:
- _is_comfyui_directory() structural verification
- _load_module() centralized importlib isolation
- get_comfyui_path() multi-strategy resolution
- sys.path idempotence (no remove/re-insert gap)
- Security: shadowing attack resistance
- Logging hygiene (no print() path leaks)
"""

import os
import sys
import tempfile
import types
import unittest
from io import StringIO
from unittest.mock import patch

# Real ComfyUI checkout for integration-style unit tests (parent of this repo)
_REAL_COMFYUI = os.path.realpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "ComfyUI")
)


class TestLoadModule(unittest.TestCase):
    """Tests for _load_module() centralized importlib isolation."""

    def tearDown(self):
        # Clean up sys.modules cache between tests to avoid cross-test pollution
        mod_names_to_clean = [
            name for name in sys.modules if name.startswith("_test_mod_")
        ]
        for name in mod_names_to_clean:
            del sys.modules[name]

    def test_loads_module_from_explicit_file_path(self):
        """Given a valid .py file, loads the module and returns it with expected attributes."""
        from comfyui_to_python.node_runtime import _load_module

        # Use a simple self-contained module (nodes.py requires torch)
        with tempfile.TemporaryDirectory() as tmpdir:
            mod_file = os.path.join(tmpdir, "mymodule.py")
            with open(mod_file, "w") as f:
                f.write("VALUE = 42\nNAME = 'test_module'\n")

            mod = _load_module("_test_mod_simple", mod_file)
        self.assertIsNotNone(mod)
        self.assertEqual(mod.VALUE, 42)
        self.assertEqual(mod.NAME, "test_module")

    def test_returns_none_for_missing_file(self):
        """Given a nonexistent file path, returns None without raising."""
        from comfyui_to_python.node_runtime import _load_module

        result = _load_module("_test_mod_missing", "/nonexistent/path/module.py")
        self.assertIsNone(result)


class TestShadowingResistance(unittest.TestCase):
    """Security: _load_module() must ignore shadowed modules at sys.path[0]."""

    def tearDown(self):
        # Clean up sys.modules cache between tests
        mod_names_to_clean = [
            name for name in sys.modules if name.startswith("_sec_test_")
        ]
        for name in mod_names_to_clean:
            del sys.modules[name]

    def test_ignores_shadowed_main_at_syspath(self):
        """Given a malicious main.py at sys.path[0], _load_module() loads from verified path."""
        from comfyui_to_python.node_runtime import _load_module

        with tempfile.TemporaryDirectory() as tmpdir:
            # Legitimate module
            legit_file = os.path.join(tmpdir, "legit_main.py")
            with open(legit_file, "w") as f:
                f.write("ORIGIN = 'legitimate'\n")

            # Malicious shadow at sys.path[0]
            attack_dir = os.path.join(tmpdir, "attack")
            os.makedirs(attack_dir)
            attack_file = os.path.join(attack_dir, "main.py")
            with open(attack_file, "w") as f:
                f.write("ORIGIN = 'malicious'\n")

            # Insert malicious path at sys.path[0]
            old_path = sys.path[:]
            try:
                sys.path.insert(0, attack_dir)
                # _load_module with explicit legit path must return legitimate module
                mod = _load_module("_sec_test_main", legit_file)
            finally:
                sys.path[:] = old_path

        self.assertIsNotNone(mod)
        self.assertEqual(mod.ORIGIN, "legitimate")

    def test_ignores_shadowed_nodes_at_syspath(self):
        """Given a malicious nodes.py at sys.path[0], _load_module() loads from verified path."""
        from comfyui_to_python.node_runtime import _load_module

        with tempfile.TemporaryDirectory() as tmpdir:
            # Legitimate module
            legit_file = os.path.join(tmpdir, "legit_nodes.py")
            with open(legit_file, "w") as f:
                f.write("NODE_CLASS_MAPPINGS = {'RealNode': 'real'}\n")

            # Malicious shadow at sys.path[0]
            attack_dir = os.path.join(tmpdir, "attack")
            os.makedirs(attack_dir)
            attack_file = os.path.join(attack_dir, "nodes.py")
            with open(attack_file, "w") as f:
                f.write("NODE_CLASS_MAPPINGS = {'FakeNode': 'malicious'}\n")

            old_path = sys.path[:]
            try:
                sys.path.insert(0, attack_dir)
                mod = _load_module("_sec_test_nodes", legit_file)
            finally:
                sys.path[:] = old_path

        self.assertIsNotNone(mod)
        self.assertEqual(mod.NODE_CLASS_MAPPINGS, {"RealNode": "real"})


class TestSysPathIdempotence(unittest.TestCase):
    """Tests for sys.path idempotence — no remove/re-insert gap."""

    def test_add_comfyui_idempotent_no_remove_insert(self):
        """Repeated calls to add_comfyui_directory_to_sys_path() are insert-once only."""
        from comfyui_to_python.node_runtime import (
            add_comfyui_directory_to_sys_path,
        )

        with patch.dict("os.environ", {"COMFYUI_PATH": _REAL_COMFYUI}, clear=False):
            before_length = len(sys.path)
            add_comfyui_directory_to_sys_path()
            after_first = len(sys.path)

            # Second call — must not change sys.path at all (no remove+re-insert)
            add_comfyui_directory_to_sys_path()
            after_second = len(sys.path)

        self.assertEqual(after_first, after_second, "sys.path changed on second call")
        # ComfyUI should be on sys.path
        self.assertIn(_REAL_COMFYUI, sys.path)

    def test_import_custom_nodes_no_gap_window(self):
        """import_custom_nodes() must never remove ComfyUI from sys.path during execution."""
        import inspect
        from comfyui_to_python.node_runtime import import_custom_nodes

        source = inspect.getsource(import_custom_nodes)
        self.assertNotIn(
            "sys.path.remove",
            source,
            "import_custom_nodes() must not remove ComfyUI from sys.path (gap window)",
        )

    def test_no_print_statements_in_node_runtime(self):
        """node_runtime.py must use logging, not print(), to avoid path leaks to stdout."""
        import inspect
        from comfyui_to_python import node_runtime

        source = inspect.getsource(node_runtime)
        self.assertNotIn(
            "print(",
            source,
            "node_runtime.py must not use print() — use logging.DEBUG instead",
        )


class TestGeneratedScriptIsolation(unittest.TestCase):
    """Tests for generated script bootstrap (Phase 3)."""

    def test_generated_script_embeds_load_module(self):
        """render.py must embed _load_module() in generated scripts."""
        from comfyui_to_python.generator.render import WorkflowRenderer
        from comfyui_to_python.generator.model import GenerationPlan

        plan = GenerationPlan(
            workflow_data={"1": {"class_type": "CheckpointLoaderSimple"}},
            metadata_workflow_data=None,
            custom_nodes=False,
            import_statements={},
            special_functions_code=[],
            loop_code=["result = some_node()"],
            queue_size=1,
        )
        renderer = WorkflowRenderer()
        generated = renderer.render(plan)

        self.assertIn("_load_module", generated, "Generated script must embed _load_module()")
        self.assertIn(
            "spec_from_file_location",
            generated,
            "Generated script must use importlib isolation",
        )

    def test_generated_script_no_bare_comfyui_imports(self):
        """Generated scripts must have zero bare imports of ComfyUI internals."""
        from comfyui_to_python.generator.render import WorkflowRenderer
        from comfyui_to_python.generator.model import GenerationPlan

        plan = GenerationPlan(
            workflow_data={"1": {"class_type": "CheckpointLoaderSimple"}},
            metadata_workflow_data=None,
            custom_nodes=True,
            import_statements={},
            special_functions_code=[],
            loop_code=["result = some_node()"],
            queue_size=1,
        )
        renderer = WorkflowRenderer()
        generated = renderer.render(plan)

        # These bare imports must NOT appear in generated output
        bare_imports = [
            "from main import",
            "from utils.extra_config import",
            "import execution",
            "import server",
            "from nodes import",
            "import comfy.options",
            "from comfy.cli_args import",
        ]
        for bare in bare_imports:
            self.assertNotIn(
                bare,
                generated,
                f"Generated script must not contain bare import: {bare}",
            )


class TestGetComfyuiPath(unittest.TestCase):
    """Tests for get_comfyui_path() multi-strategy resolution."""

    def test_resolves_via_valid_comfyui_path_env(self):
        """Given COMFYUI_PATH env var set to valid ComfyUI dir, returns that path."""
        from comfyui_to_python.node_runtime import get_comfyui_path

        with patch.dict("os.environ", {"COMFYUI_PATH": _REAL_COMFYUI}, clear=False):
            result = get_comfyui_path()
        self.assertEqual(result, _REAL_COMFYUI)

    def test_falls_through_to_next_strategy_when_env_invalid(self):
        """Given invalid COMFYUI_PATH (no nodes.py), rejects and falls through."""
        from comfyui_to_python.node_runtime import get_comfyui_path

        with patch.dict(
            "os.environ", {"COMFYUI_PATH": "/tmp/not-comfyui"}, clear=False
        ):
            result = get_comfyui_path()
        # The invalid path must be rejected (not returned as-is)
        self.assertNotEqual(result, "/tmp/not-comfyui")
        # In standalone/dev setups, no strategy may succeed -> None is valid
        # In ComfyUI/custom_nodes/ install, relative strategy would find it


class TestIsComfyuiDirectory(unittest.TestCase):
    """Tests for _is_comfyui_directory() structural verification."""

    def test_returns_true_for_real_comfyui_checkout(self):
        """Given a real ComfyUI checkout with nodes.py, returns True."""
        from comfyui_to_python.node_runtime import _is_comfyui_directory

        self.assertTrue(_is_comfyui_directory(_REAL_COMFYUI))

    def test_rejects_directory_lacking_markers(self):
        """Given a directory without nodes.py, returns False."""
        from comfyui_to_python.node_runtime import _is_comfyui_directory

        with tempfile.TemporaryDirectory() as tmpdir:
            # Empty directory has no ComfyUI markers
            self.assertFalse(_is_comfyui_directory(tmpdir))

    def test_rejects_nonexistent_path(self):
        """Given a nonexistent path, returns False."""
        from comfyui_to_python.node_runtime import _is_comfyui_directory

        self.assertFalse(_is_comfyui_directory("/nonexistent/path/to/comfyui"))


if __name__ == "__main__":
    unittest.main()
