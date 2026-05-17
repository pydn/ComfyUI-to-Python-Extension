"""Tests for CLI args propagation through ComfyUI's import chain.

Ensures that parsed CLI arguments (e.g., --cpu) persist in sys.modules so that
when ComfyUI's internal chain re-imports comfy.cli_args, it gets the cached
instance with already-parsed args instead of a fresh copy with empty argv.
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import patch


class TestLoadModuleCachesInSysModules(unittest.TestCase):
    """Tests for _load_module - verifies modules are cached in sys.modules."""

    def tearDown(self):
        # Clean up test modules from sys.modules
        for name in list(sys.modules):
            if name.startswith("_test_cli_"):
                del sys.modules[name]

    def test_load_module_caches_under_canonical_name(self):
        """Given _load_module with canonical name, module is cached in sys.modules."""
        from comfyui_to_python.node_runtime import _load_module

        with tempfile.TemporaryDirectory() as tmpdir:
            mod_file = os.path.join(tmpdir, "_test_cli_opts.py")
            with open(mod_file, "w") as f:
                f.write("VALUE = 42\n")

            mod = _load_module("comfy.options", mod_file)
        self.assertIsNotNone(mod)
        self.assertEqual(mod.VALUE, 42)
        # Module must remain cached under canonical name
        self.assertIn("comfy.options", sys.modules)
        self.assertIs(sys.modules["comfy.options"], mod)

    def test_reimport_via_load_module_returns_cached_instance(self):
        """Second _load_module() for same name returns cached module with mutations."""
        from comfyui_to_python.node_runtime import _load_module

        with tempfile.TemporaryDirectory() as tmpdir:
            mod_file = os.path.join(tmpdir, "_test_cli_args.py")
            with open(mod_file, "w") as f:
                f.write("parsed_flags = []\n")

            first = _load_module("comfy.cli_args", mod_file)
            first.parsed_flags.append("--cpu")  # Simulate args parsing

            # Re-import (ComfyUI's internal chain) - must return same instance
            second = _load_module("comfy.cli_args", mod_file)

        self.assertIs(first, second)
        self.assertIn("--cpu", second.parsed_flags)

    def test_reimport_returns_same_object_identity(self):
        """Cached module identity is preserved (is, not ==)."""
        from comfyui_to_python.node_runtime import _load_module

        with tempfile.TemporaryDirectory() as tmpdir:
            mod_file = os.path.join(tmpdir, "_test_cli_identity.py")
            with open(mod_file, "w") as f:
                f.write("DATA = 'original'\n")

            first = _load_module("_test_cli_mod", mod_file)
            first.DATA = "mutated"

            second = _load_module("_test_cli_mod", mod_file)
        self.assertIs(first, second)
        self.assertEqual(second.DATA, "mutated")


class TestLoadModuleTempRemovesFromSysModules(unittest.TestCase):
    """Tests for _load_module_temp - removes modules from sys.modules.

    Documents why _bootstrap_import is preferred for options/cli_args:
    _load_module_temp removes the module so ComfyUI's chain re-imports fresh.
    """

    def tearDown(self):
        for name in list(sys.modules):
            if name.startswith("_test_temp_"):
                del sys.modules[name]

    def test_load_module_temp_removes_from_sys_modules(self):
        """After _load_module_temp(), the module is removed from sys.modules."""
        from comfyui_to_python.node_runtime import _load_module_temp

        with tempfile.TemporaryDirectory() as tmpdir:
            mod_file = os.path.join(tmpdir, "_test_temp_mod.py")
            with open(mod_file, "w") as f:
                f.write("VALUE = 123\n")

            mod = _load_module_temp("_test_temp_mod", mod_file)
        self.assertIsNotNone(mod)
        # This is the problematic behavior that caused CLI args to be lost
        self.assertNotIn(
            "_test_temp_mod",
            sys.modules,
            "_load_module_temp intentionally removes from sys.modules",
        )

    def test_load_module_temp_causes_stale_reimport(self):
        """When cli_args is loaded via _load_module_temp, re-import gets fresh copy.

        Demonstrates the bug: _load_module_temp removes module from sys.modules,
        so the next import creates a new instance without parsed args.
        """
        from comfyui_to_python.node_runtime import _load_module, _load_module_temp

        with tempfile.TemporaryDirectory() as tmpdir:
            mod_file = os.path.join(tmpdir, "_test_temp_stale.py")
            with open(mod_file, "w") as f:
                f.write("parsed_args = []\n")

            # First import via _load_module_temp (old bootstrap behavior)
            mod1 = _load_module_temp("_test_temp_stale", mod_file)
            mod1.parsed_args.append("--cpu")

            # Re-import (ComfyUI's internal chain) - gets FRESH instance, no args!
            mod2 = _load_module("_test_temp_stale", mod_file)

        self.assertIsNot(mod1, mod2)  # Different instances
        self.assertNotIn("--cpu", mod2.parsed_args)  # Args lost!


class TestDiscoverComfyuiCliOptions(unittest.TestCase):
    """Tests for _discover_comfyui_cli_options - dynamic parser inspection."""

    def tearDown(self):
        # Reset global cache so tests are isolated.
        # After refactor, the actual cache lives in runtime/bootstrap.py;
        # reset both to ensure full isolation.
        import comfyui_to_python.node_runtime as rt
        from comfyui_to_python.runtime import bootstrap as bs

        rt._DISCOVERED_OPTIONS = None
        bs._DISCOVERED_OPTIONS = None

    def test_returns_known_boolean_flags(self):
        """Discovered options include known boolean flags like --cpu."""
        from comfyui_to_python.node_runtime import _discover_comfyui_cli_options

        # Force discovery to work even without ComfyUI by mocking parser
        import argparse

        mock_parser = argparse.ArgumentParser()
        mock_parser.add_argument("--cpu", action="store_true")
        mock_parser.add_argument("--lowvram", action="store_true")

        with patch(
            "comfyui_to_python.runtime.bootstrap._bootstrap_import",
            return_value=type("FakeMod", (), {"parser": mock_parser})(),
        ):
            known, _ = _discover_comfyui_cli_options()
        self.assertIn("--cpu", known)
        self.assertIn("--lowvram", known)

    def test_returns_value_taking_flags(self):
        """Discovered value_taking set includes flags that take arguments."""
        from comfyui_to_python.node_runtime import _discover_comfyui_cli_options

        import argparse

        mock_parser = argparse.ArgumentParser()
        mock_parser.add_argument("--cpu", action="store_true")
        mock_parser.add_argument("--reserve-vram", type=float)
        mock_parser.add_argument("--cuda-device", type=int)

        with patch(
            "comfyui_to_python.runtime.bootstrap._bootstrap_import",
            return_value=type("FakeMod", (), {"parser": mock_parser})(),
        ):
            known, value_taking = _discover_comfyui_cli_options()
        self.assertIn("--reserve-vram", value_taking)
        self.assertIn("--cuda-device", value_taking)
        # --cpu is boolean (store_true), not in value_taking
        self.assertNotIn("--cpu", value_taking)

    def test_caches_result(self):
        """Second call returns cached result without re-importing."""
        from comfyui_to_python.node_runtime import _discover_comfyui_cli_options

        import argparse

        mock_parser = argparse.ArgumentParser()
        mock_parser.add_argument("--cpu", action="store_true")

        call_count = [0]

        def counting_import(name):
            call_count[0] += 1
            return type("FakeMod", (), {"parser": mock_parser})()

        with patch(
            "comfyui_to_python.runtime.bootstrap._bootstrap_import",
            side_effect=counting_import,
        ):
            _discover_comfyui_cli_options()
            _discover_comfyui_cli_options()

        self.assertEqual(call_count[0], 1, "Should only import once (cached)")

    def test_returns_empty_when_no_parser(self):
        """Returns empty sets when comfy.cli_args has no parser attribute."""
        from comfyui_to_python.node_runtime import _discover_comfyui_cli_options

        with patch(
            "comfyui_to_python.runtime.bootstrap._bootstrap_import",
            return_value=type("FakeMod", (), {})(),
        ):
            known, value_taking = _discover_comfyui_cli_options()
        self.assertEqual(known, frozenset())
        self.assertEqual(value_taking, frozenset())

    def test_strips_bracket_defaults_from_option_names(self):
        """Option names with inline defaults (e.g. '--listen [IP]') are stripped."""
        from comfyui_to_python.node_runtime import _discover_comfyui_cli_options

        import argparse

        mock_parser = argparse.ArgumentParser()
        mock_parser.add_argument("--listen", type=str, default="127.0.0.1")

        # Manually add a bracket-style option string (as argparse shows in help)
        for action in mock_parser._actions:
            if "--listen" in action.option_strings:
                action.option_strings = ["--listen"]
                break

        with patch(
            "comfyui_to_python.runtime.bootstrap._bootstrap_import",
            return_value=type("FakeMod", (), {"parser": mock_parser})(),
        ):
            known, _ = _discover_comfyui_cli_options()
        self.assertIn("--listen", known)


class TestFilterComfyuiArgs(unittest.TestCase):
    """Tests for _filter_comfyui_args - strips non-ComfyUI flags from argv."""

    def setUp(self):
        import comfyui_to_python.node_runtime as rt
        from comfyui_to_python.runtime import bootstrap as bs

        self._original_cache = rt._DISCOVERED_OPTIONS
        # Pre-populate cache so filter doesn't try to import ComfyUI.
        # Set on BOTH node_runtime (re-export) and bootstrap (actual storage).
        rt._DISCOVERED_OPTIONS = (
            frozenset(
                [
                    "--cpu",
                    "--lowvram",
                    "--reserve-vram",
                    "--cuda-device",
                    "--verbose",
                    "--front-end-version",
                ]
            ),
            frozenset(
                [
                    "--reserve-vram",
                    "--cuda-device",
                    "--verbose",
                    "--front-end-version",
                ]
            ),
        )
        bs._DISCOVERED_OPTIONS = rt._DISCOVERED_OPTIONS

    def tearDown(self):
        import comfyui_to_python.node_runtime as rt
        from comfyui_to_python.runtime import bootstrap as bs

        rt._DISCOVERED_OPTIONS = self._original_cache
        bs._DISCOVERED_OPTIONS = self._original_cache

    def test_preserves_known_flags(self):
        """Known ComfyUI flags like --cpu are preserved."""
        from comfyui_to_python.generator.generated_helpers import _filter_comfyui_args

        result = _filter_comfyui_args(["script.py", "--cpu"])
        self.assertEqual(result, ["script.py", "--cpu"])

    def test_strips_unknown_flags(self):
        """Unknown flags are removed."""
        from comfyui_to_python.generator.generated_helpers import _filter_comfyui_args

        result = _filter_comfyui_args(
            ["script.py", "--internal-export", "--cpu", "--unknown-flag"]
        )
        self.assertEqual(result, ["script.py", "--cpu"])

    def test_strips_unknown_flags_with_values(self):
        """Unknown flags and their values are both removed."""
        from comfyui_to_python.generator.generated_helpers import _filter_comfyui_args

        result = _filter_comfyui_args(["script.py", "--some-value", "foo", "--cpu"])
        self.assertEqual(result, ["script.py", "--cpu"])

    def test_preserves_flag_values_for_known_flags(self):
        """Known flags that expect values keep their values."""
        from comfyui_to_python.generator.generated_helpers import _filter_comfyui_args

        result = _filter_comfyui_args(["script.py", "--reserve-vram", "4096"])
        self.assertEqual(result, ["script.py", "--reserve-vram", "4096"])

    def test_preserves_inline_flag_values(self):
        """Flags with inline values (--flag=value) are preserved as-is."""
        from comfyui_to_python.generator.generated_helpers import _filter_comfyui_args

        result = _filter_comfyui_args(["script.py", "--cuda-device=0"])
        self.assertEqual(result, ["script.py", "--cuda-device=0"])

    def test_handles_empty_argv(self):
        """Empty argv returns empty result."""
        from comfyui_to_python.generator.generated_helpers import _filter_comfyui_args

        result = _filter_comfyui_args([])
        self.assertEqual(result, [])

    def test_preserves_positional_args(self):
        """Positional (non-flag) args are preserved."""
        from comfyui_to_python.generator.generated_helpers import _filter_comfyui_args

        result = _filter_comfyui_args(["script.py", "output.png"])
        self.assertEqual(result, ["script.py", "output.png"])

    def test_boolean_flags_dont_consume_next_arg(self):
        """Boolean flags like --cpu don't consume the next positional arg."""
        from comfyui_to_python.generator.generated_helpers import _filter_comfyui_args

        result = _filter_comfyui_args(["script.py", "--cpu", "output.png"])
        self.assertEqual(result, ["script.py", "--cpu", "output.png"])

    def test_strips_single_char_flags(self):
        """Single-char flags (e.g. -v from pytest) are stripped."""
        from comfyui_to_python.generator.generated_helpers import _filter_comfyui_args

        result = _filter_comfyui_args(["script.py", "-v", "--cpu", "-x", "--lowvram"])
        self.assertEqual(result, ["script.py", "--cpu", "--lowvram"])

    def test_mixed_known_and_unknown(self):
        """Mix of known, unknown, and single-char flags is correctly filtered."""
        from comfyui_to_python.generator.generated_helpers import _filter_comfyui_args

        result = _filter_comfyui_args(
            [
                "script.py",
                "--cpu",
                "-s",
                "--unknown-thing",
                "foo",
                "--reserve-vram",
                "8",
            ]
        )
        self.assertEqual(result, ["script.py", "--cpu", "--reserve-vram", "8"])


class TestBootstrapUsesBootstrapImport(unittest.TestCase):
    """Verify bootstrap_comfyui_runtime uses _bootstrap_import (not _load_module_temp).

    Regression test: if someone accidentally reverts to _load_module_temp for
    options/cli_args, the CLI args will be lost on re-import.
    """

    def test_bootstrap_uses_bootstrap_import_for_options(self):
        """bootstrap_comfyui_runtime must use _bootstrap_import for options."""
        import inspect
        from comfyui_to_python.node_runtime import bootstrap_comfyui_runtime

        source = inspect.getsource(bootstrap_comfyui_runtime)
        self.assertIn('_bootstrap_import("comfy.options")', source)
        self.assertIn('_bootstrap_import("comfy.cli_args")', source)

    def test_bootstrap_uses_bootstrap_import_for_cli_args(self):
        """bootstrap_comfyui_runtime must use _bootstrap_import for cli_args."""
        import inspect
        from comfyui_to_python.node_runtime import bootstrap_comfyui_runtime

        source = inspect.getsource(bootstrap_comfyui_runtime)
        # Must NOT use _load_module with file paths for options/cli_args
        # (namespace packages don't work with file-path loading)
        self.assertNotIn('"comfy.options", os.path.join', source)


class TestGeneratedScriptEmbedsBootstrap(unittest.TestCase):
    """Verify generated scripts include bootstrap functions with correct behavior."""

    def test_generated_script_has_filter_comfyui_args(self):
        """Generated scripts must embed _filter_comfyui_args."""
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

        self.assertIn("_filter_comfyui_args", generated)
        self.assertIn("_discover_comfyui_cli_options", generated)
        self.assertIn("sys.argv = _filter_comfyui_args(sys.argv)", generated)

    def test_generated_script_filters_argv_before_bootstrap(self):
        """Generated script filters argv before calling options enable_args_parsing."""
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

        # _filter_comfyui_args must appear before enable_args_parsing
        filter_pos = generated.find("_filter_comfyui_args")
        parsing_pos = generated.find("enable_args_parsing()")
        self.assertLess(
            filter_pos,
            parsing_pos,
            "argv filtering must occur before options enable_args_parsing",
        )


if __name__ == "__main__":
    unittest.main()
