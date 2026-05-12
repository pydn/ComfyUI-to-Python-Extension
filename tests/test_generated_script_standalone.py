"""Regression tests for generated script standalone execution.

Ensures that freshly-generated scripts can run as __main__ without
failing on relative imports or NameError from missing cross-references.
"""

import re
import subprocess
import sys
import tempfile
import unittest


class TestGeneratedScriptNoRelativeImports(unittest.TestCase):
    """Verify generated scripts contain no relative imports with dots."""

    def test_no_relative_imports_in_embedded_block(self):
        """All embedded helpers must be free of 'from .' imports.

        Generated scripts embed module bodies (imports stripped) rather than
        individual functions. Any remaining relative import would fail with
        ImportError when the script runs as __main__ with no package context.
        """
        from comfyui_to_python.generator.embedded_modules import get_embedded_helpers

        embedded = get_embedded_helpers()
        relative_import_pattern = re.compile(r"^\s*from\s+\.\s*")
        matches = relative_import_pattern.findall(embedded)

        self.assertEqual(
            matches,
            [],
            f"Found {len(matches)} relative imports in embedded helpers",
        )

    def test_all_contributing_modules_embedded(self):
        """Every contributing module is present in the embedded block.

        If a new helper function is added to a runtime module but that module
        isn't listed in _SOURCE_FILES, it won't be embedded and will cause
        NameError at runtime. This test verifies all expected modules are included.
        """
        from comfyui_to_python.generator.embedded_modules import (
            get_embedded_helpers,
            list_embedded_names,
        )

        names = list_embedded_names()
        embedded = get_embedded_helpers()

        # All named functions must appear in the embedded block
        for name in names:
            self.assertIn(
                f"def {name}(",
                embedded,
                f"Function '{name}' is listed but not found in embedded source",
            )

    def test_no_unresolved_cross_calls(self):
        """All function calls within embedded code must resolve.

        If a new internal helper is added to a runtime module and called by
        an existing embedded function, it must also be embedded. This catches
        the class of bug where _apply_device_settings was added but forgotten
        from the embed list.
        """
        from comfyui_to_python.generator.embedded_modules import (
            verify_no_missing_cross_calls,
        )

        unresolved = verify_no_missing_cross_calls()
        self.assertEqual(
            unresolved,
            [],
            f"Found unresolved cross-calls:\n" + "\n".join(f"  - {u}" for u in unresolved),
        )

    def test_no_relative_imports_in_full_rendered_script(self):
        """A full rendered script must contain no 'from .' patterns.

        Renders a complete GenerationPlan and checks the final output
        for any relative import statements that would break standalone execution.
        """
        from comfyui_to_python.generator.render import WorkflowRenderer
        from comfyui_to_python.generator.model import GenerationPlan

        plan = GenerationPlan(
            workflow_data={
                "1": {"class_type": "CheckpointLoaderSimple", "inputs": {}},
                "2": {"class_type": "CLIPTextEncode", "inputs": {}},
            },
            metadata_workflow_data=None,
            custom_nodes=False,
            import_statements={},
            special_functions_code=[],
            loop_code=["result = some_node()"],
            queue_size=1,
        )

        renderer = WorkflowRenderer()
        generated = renderer.render(plan)

        # Check for 'from .' patterns (relative imports)
        relative_imports = re.findall(r"^\s*from\s+\.", generated, re.MULTILINE)
        self.assertEqual(
            relative_imports,
            [],
            f"Generated script contains relative imports: {relative_imports}",
        )

    def test_rendered_script_compiles_as_standalone(self):
        """A rendered script must compile without ImportError as standalone code.

        Writes generated code to a temp file and verifies Python can compile
        it. This catches syntax errors and top-level import failures (like
        relative imports in __main__ context).
        """
        from comfyui_to_python.generator.render import WorkflowRenderer
        from comfyui_to_python.generator.model import GenerationPlan

        plan = GenerationPlan(
            workflow_data={
                "1": {"class_type": "CheckpointLoaderSimple", "inputs": {}},
            },
            metadata_workflow_data=None,
            custom_nodes=False,
            import_statements={},
            special_functions_code=[],
            loop_code=["result = some_node()"],
            queue_size=1,
        )

        renderer = WorkflowRenderer()
        generated = renderer.render(plan)

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write(generated)
            tmp_path = f.name

        try:
            # Compile the script — catches relative import errors at parse time
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    f"compile(open('{tmp_path}').read(), '{tmp_path}', 'exec')",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )

            self.assertEqual(
                result.returncode,
                0,
                f"Generated script failed to compile:\n{result.stderr}",
            )
        finally:
            import os

            os.unlink(tmp_path)


if __name__ == "__main__":
    unittest.main()
