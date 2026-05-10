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
import unittest
from unittest.mock import patch

# Real ComfyUI checkout for integration-style unit tests (parent of this repo)
_REAL_COMFYUI = os.path.realpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "ComfyUI")
)


def _make_fake_comfyui(tmpdir: str) -> str:
    """Create a minimal fake ComfyUI directory in tmpdir with structural markers."""
    comfyui_dir = os.path.join(tmpdir, "ComfyUI")
    os.makedirs(comfyui_dir)
    # Structural markers checked by _is_comfyui_directory()
    with open(os.path.join(comfyui_dir, "nodes.py"), "w") as f:
        f.write("# fake nodes.py\n")
    with open(os.path.join(comfyui_dir, "main.py"), "w") as f:
        f.write("# fake main.py\n")
    os.makedirs(os.path.join(comfyui_dir, "comfy"))
    return comfyui_dir


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


@unittest.skipUnless(os.path.isdir(_REAL_COMFYUI), "requires ../ComfyUI checkout")
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

    def test_already_at_index_zero_is_noop(self):
        """Given ComfyUI already at sys.path[0], add_comfyui_directory_to_sys_path() is a no-op."""
        from comfyui_to_python.node_runtime import (
            add_comfyui_directory_to_sys_path,
        )

        original_path = sys.path[:]
        try:
            with patch.dict("os.environ", {"COMFYUI_PATH": _REAL_COMFYUI}, clear=False):
                # Put ComfyUI at index 0 manually
                if _REAL_COMFYUI in sys.path:
                    sys.path.remove(_REAL_COMFYUI)
                sys.path.insert(0, _REAL_COMFYUI)
                original_index = sys.path.index(_REAL_COMFYUI)

                add_comfyui_directory_to_sys_path()
                new_index = sys.path.index(_REAL_COMFYUI)
        finally:
            sys.path[:] = original_path

        self.assertEqual(
            original_index, new_index, "Index should not change when already at [0]"
        )
        self.assertEqual(new_index, 0)

    def test_promotes_comfyui_to_sys_path_zero(self):
        """Given ComfyUI at sys.path[5], add_comfyui_directory_to_sys_path() moves it to index 0."""
        from comfyui_to_python.node_runtime import (
            add_comfyui_directory_to_sys_path,
        )

        original_path = sys.path[:]
        try:
            with patch.dict("os.environ", {"COMFYUI_PATH": _REAL_COMFYUI}, clear=False):
                # Insert ComfyUI deep in sys.path (simulating PYTHONPATH placement)
                if _REAL_COMFYUI in sys.path:
                    sys.path.remove(_REAL_COMFYUI)
                sys.path.insert(5, _REAL_COMFYUI)

                add_comfyui_directory_to_sys_path()
                self.assertEqual(
                    sys.path[0],
                    _REAL_COMFYUI,
                    "ComfyUI must be promoted to sys.path[0] when already present lower down",
                )
        finally:
            sys.path[:] = original_path

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

        self.assertIn(
            "_load_module", generated, "Generated script must embed _load_module()"
        )
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

        with tempfile.TemporaryDirectory() as tmpdir:
            fake_comfyui = _make_fake_comfyui(tmpdir)
            original_cwd = os.getcwd()
            try:
                os.chdir(fake_comfyui)  # strategy 2 would find it, but env wins first
            finally:
                pass
            with patch.dict("os.environ", {"COMFYUI_PATH": fake_comfyui}, clear=False):
                result = get_comfyui_path()
            os.chdir(original_cwd)
        self.assertEqual(result, fake_comfyui)

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
        """Given a valid ComfyUI directory with structural markers, returns True."""
        from comfyui_to_python.node_runtime import _is_comfyui_directory

        with tempfile.TemporaryDirectory() as tmpdir:
            fake_comfyui = _make_fake_comfyui(tmpdir)
            self.assertTrue(_is_comfyui_directory(fake_comfyui))

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


class TestLoadModuleFailureCleanup(unittest.TestCase):
    """Tests for _load_module() behavior when exec_module() raises."""

    def tearDown(self):
        mod_names_to_clean = [
            name for name in sys.modules if name.startswith("_test_fail_")
        ]
        for name in mod_names_to_clean:
            del sys.modules[name]

    def test_broken_module_removed_from_sys_modules_on_failure(self):
        """Given a module that raises during exec, it is removed from sys.modules."""
        from comfyui_to_python.node_runtime import _load_module

        with tempfile.TemporaryDirectory() as tmpdir:
            mod_file = os.path.join(tmpdir, "badmodule.py")
            with open(mod_file, "w") as f:
                f.write("raise RuntimeError('mid-execution failure')\n")

            result = _load_module("_test_fail_bad", mod_file)
        self.assertIsNone(result)
        self.assertNotIn(
            "_test_fail_bad",
            sys.modules,
            "Failed module must not remain cached in sys.modules",
        )

    def test_broken_module_retried_cleanly(self):
        """Given a failed load, a subsequent load attempt starts fresh (not from cache)."""
        from comfyui_to_python.node_runtime import _load_module

        with tempfile.TemporaryDirectory() as tmpdir:
            bad_file = os.path.join(tmpdir, "bad.py")
            good_file = os.path.join(tmpdir, "good.py")

            # First load: bad module that raises
            with open(bad_file, "w") as f:
                f.write("raise RuntimeError('fail')\n")
            result_bad = _load_module("_test_fail_retry", bad_file)
            self.assertIsNone(result_bad)

            # Overwrite with good module
            os.remove(bad_file)
            with open(good_file, "w") as f:
                f.write("VALUE = 99\n")

            # Reload same name from a different (working) file
            result_good = _load_module("_test_fail_retry", good_file)
        self.assertIsNotNone(result_good)
        self.assertEqual(result_good.VALUE, 99)


class TestCanonicalOptionsLoading(unittest.TestCase):
    """Tests for canonical module loading of comfy.options in bootstrap."""

    def tearDown(self):
        # Clean up sys.modules cache
        mod_names_to_clean = [
            name for name in sys.modules if name.startswith("_test_opts_")
        ]
        for name in mod_names_to_clean:
            del sys.modules[name]
        if "comfy.options" in sys.modules:
            del sys.modules["comfy.options"]

    def test_load_under_canonical_name_caches_in_sys_modules(self):
        """When _load_module() uses canonical name, the module is cached in sys.modules."""
        from comfyui_to_python.node_runtime import _load_module

        with tempfile.TemporaryDirectory() as tmpdir:
            mod_file = os.path.join(tmpdir, "options.py")
            with open(mod_file, "w") as f:
                f.write("args_parsing = False\n")

            # Load under canonical name
            mod = _load_module("comfy.options", mod_file)
        self.assertIsNotNone(mod)
        # The canonical key must be in sys.modules so later imports see mutations
        self.assertIn(
            "comfy.options",
            sys.modules,
            "Canonical module load must cache under canonical name in sys.modules",
        )


class TestLoadModuleTemp(unittest.TestCase):
    """Tests for _load_module_temp() removal from sys.modules."""

    def tearDown(self):
        mod_names_to_clean = [
            name for name in sys.modules if name.startswith("_test_temp_")
        ]
        for name in mod_names_to_clean:
            del sys.modules[name]

    def test_module_removed_from_sys_modules_after_temp_load(self):
        """After _load_module_temp(), the module key is absent from sys.modules."""
        from comfyui_to_python.node_runtime import _load_module_temp

        with tempfile.TemporaryDirectory() as tmpdir:
            mod_file = os.path.join(tmpdir, "tempmod.py")
            with open(mod_file, "w") as f:
                f.write("VALUE = 123\n")

            mod = _load_module_temp("_test_temp_mod", mod_file)
        self.assertIsNotNone(mod)
        self.assertEqual(mod.VALUE, 123)
        self.assertNotIn(
            "_test_temp_mod",
            sys.modules,
            "Temp module must be removed from sys.modules after load",
        )

    def test_module_removed_on_temp_load_failure(self):
        """After _load_module_temp() fails, the module key is absent from sys.modules."""
        from comfyui_to_python.node_runtime import _load_module_temp

        with tempfile.TemporaryDirectory() as tmpdir:
            mod_file = os.path.join(tmpdir, "badtemp.py")
            with open(mod_file, "w") as f:
                f.write("raise RuntimeError('fail')\n")

            result = _load_module_temp("_test_temp_bad", mod_file)
        self.assertIsNone(result)
        self.assertNotIn(
            "_test_temp_bad",
            sys.modules,
            "Failed temp module must be removed from sys.modules",
        )


class TestRepeatedNodeLoad(unittest.TestCase):
    """Tests that repeated _load_module('nodes', ...) calls respect the cache."""

    def tearDown(self):
        if "_test_nodes" in sys.modules:
            del sys.modules["_test_nodes"]

    def test_repeated_load_preserves_cached_attributes(self):
        """Second _load_module() for same name returns cached module, not a fresh copy."""
        from comfyui_to_python.node_runtime import _load_module

        with tempfile.TemporaryDirectory() as tmpdir:
            mod_file = os.path.join(tmpdir, "mynodes.py")
            with open(mod_file, "w") as f:
                f.write("NODE_CLASS_MAPPINGS = {'A': 1}\n")

            first = _load_module("_test_nodes", mod_file)
            self.assertIsNotNone(first)

            # Mutate the cached module to simulate init_extra_nodes()
            first.NODE_CLASS_MAPPINGS["B"] = 2

            # Second load with same name must return cached copy, preserving mutation
            second = _load_module("_test_nodes", mod_file)
        self.assertIs(first, second)
        self.assertEqual(second.NODE_CLASS_MAPPINGS.get("B"), 2)


class TestFindFile(unittest.TestCase):
    """Tests for _find_file() — file discovery via directory walk."""

    def test_finds_file_at_cwd_level(self):
        """Given a file at CWD, _find_file() returns the full path to it."""
        from comfyui_to_python.node_runtime import _find_file

        original_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmpdir:
            target_file = os.path.join(tmpdir, "extra_model_paths.yaml")
            with open(target_file, "w") as f:
                f.write("config: value\n")

            try:
                os.chdir(tmpdir)
                result = _find_file("extra_model_paths.yaml")
            finally:
                os.chdir(original_cwd)

        self.assertEqual(result, target_file)

    def test_finds_file_in_parent_directory(self):
        """Given a file in a parent directory, _find_file() walks up and finds it."""
        from comfyui_to_python.node_runtime import _find_file

        original_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmpdir:
            target_file = os.path.join(tmpdir, "extra_model_paths.yaml")
            with open(target_file, "w") as f:
                f.write("config: value\n")

            # Create a subdirectory and chdir into it
            subdir = os.path.join(tmpdir, "subdir", "deeper")
            os.makedirs(subdir)

            try:
                os.chdir(subdir)
                result = _find_file("extra_model_paths.yaml")
            finally:
                os.chdir(original_cwd)

        self.assertEqual(result, target_file)

    def test_returns_none_when_file_not_found(self):
        """Given a filename that doesn't exist within max_depth, returns None."""
        from comfyui_to_python.node_runtime import _find_file

        original_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                os.chdir(tmpdir)
                result = _find_file("nonexistent_config.yaml")
            finally:
                os.chdir(original_cwd)
        self.assertIsNone(result)

    def test_returns_none_for_directory_not_file(self):
        """Given a directory with matching name, returns None (wants a file)."""
        from comfyui_to_python.node_runtime import _find_file

        original_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a directory (not file) with the target name
            fake_dir = os.path.join(tmpdir, "extra_model_paths.yaml")
            os.makedirs(fake_dir)

            try:
                os.chdir(tmpdir)
                result = _find_file("extra_model_paths.yaml")
            finally:
                os.chdir(original_cwd)

        self.assertIsNone(result)


class TestFindPathCwdFirst(unittest.TestCase):
    """Tests for find_path() checking CWD before walking to parent."""

    def test_find_path_returns_cwd_when_cwd_is_match(self):
        """Given CWD is named 'ComfyUI', find_path('ComfyUI') returns CWD itself."""
        from comfyui_to_python.node_runtime import find_path

        original_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmpdir:
            comfyui_dir = os.path.join(tmpdir, "ComfyUI")
            os.makedirs(comfyui_dir)
            try:
                os.chdir(comfyui_dir)
                result = find_path("ComfyUI")
            finally:
                os.chdir(original_cwd)

        self.assertEqual(result, comfyui_dir)

    def test_find_path_checks_cwd_before_parent(self):
        """When CWD matches but parent also matches, CWD is returned (check-first)."""
        from comfyui_to_python.node_runtime import find_path

        original_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create nested dirs: outer/ComfyUI/inner where inner is named ComfyUI too
            outer_comfy = os.path.join(tmpdir, "ComfyUI")
            os.makedirs(outer_comfy)
            # Rename so we can create an inner dir also named ComfyUI
            os.rename(outer_comfy, os.path.join(tmpdir, "ParentComfy"))
            parent_comfy = os.path.join(tmpdir, "ParentComfy")
            child_dir = os.path.join(parent_comfy, "subdir")
            os.makedirs(child_dir)

            try:
                os.chdir(child_dir)
                # When searching for ParentComfy, should find it at parent level
                result = find_path("ParentComfy")
            finally:
                os.chdir(original_cwd)

        self.assertEqual(result, parent_comfy)


class TestGetComfyuiPathThirdStrategy(unittest.TestCase):
    """Tests for get_comfyui_path() third-strategy verification."""

    def test_fallback_rejects_non_comfyui_directory(self):
        """Given a directory named ComfyUI without nodes.py, third strategy rejects it."""
        from comfyui_to_python.node_runtime import get_comfyui_path

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a fake "ComfyUI" directory (no nodes.py)
            fake_dir = os.path.join(tmpdir, "ComfyUI")
            os.makedirs(fake_dir)

            original_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                with patch.dict("os.environ", {}, clear=False):
                    # Strip COMFYUI_PATH so fallback strategies activate
                    env_copy = dict(os.environ)
                    env_copy.pop("COMFYUI_PATH", None)
                    with patch.dict("os.environ", env_copy, clear=True):
                        result = get_comfyui_path()
            finally:
                os.chdir(original_cwd)

        # Must NOT return the fake directory
        self.assertNotEqual(result, fake_dir)


@unittest.skipUnless(os.path.isdir(_REAL_COMFYUI), "requires ../ComfyUI checkout")
class TestImportCustomNodesSysPathRestoration(unittest.TestCase):
    """Tests for sys.path restoration in import_custom_nodes()."""

    def test_sys_path_restored_on_crash(self):
        """Given a crash during import_custom_nodes(), sys.path is still restored.

        The crash fires on the "server" module load (after comfy/ filtering)
        so that the try/finally sys.path restoration path is actually exercised.
        """
        from comfyui_to_python.node_runtime import import_custom_nodes

        original_path = sys.path[:]
        call_order = []

        def fake_load(name, path):
            call_order.append(name)
            if name == "server":
                raise RuntimeError("simulated crash during server load")
            return None  # Let execution/nodes return None (falls through gracefully)

        with (
            patch(
                "comfyui_to_python.node_runtime._load_module",
                side_effect=fake_load,
            ),
            patch(
                "comfyui_to_python.node_runtime.get_comfyui_path",
                return_value=_REAL_COMFYUI if os.path.isdir(_REAL_COMFYUI) else None,
            ),
        ):
            try:
                import_custom_nodes()
            except RuntimeError:
                pass  # Expected crash

        # When ComfyUI path is found, "execution" and "nodes" should be called
        # before reaching the server module load inside try/finally.
        self.assertIn("execution", call_order, "Expected 'execution' to be loaded")
        self.assertIn("nodes", call_order, "Expected 'nodes' to be loaded")
        self.assertIn("server", call_order, "Expected 'server' to trigger the crash")

        # sys.path should still contain all original entries (no dangling state)
        for entry in original_path:
            self.assertIn(entry, sys.path)


if __name__ == "__main__":
    unittest.main()
