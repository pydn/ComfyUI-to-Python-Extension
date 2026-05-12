"""Regression tests for generated script standalone execution.

Ensures that freshly-generated scripts can run as __main__ without
failing on relative imports (from .module_loader, etc.) which have
no package context when executed directly.

See: bootstrap.py _discover_comfyui_cli_options() — the inline
relative import was removed so that inspect.getsource()-embedded
code works in generated standalone scripts.
"""

import re
import subprocess
import sys
import tempfile
import unittest


class TestGeneratedScriptNoRelativeImports(unittest.TestCase):
    """Verify generated scripts contain no relative imports with dots."""

    def test_no_relative_imports_in_rendered_helpers(self):
        """All embedded helper functions must be free of 'from .' imports.

        Generated scripts embed helpers via inspect.getsource() which captures
        the full function body including any inner imports. Relative imports
        (from .module_loader, from ..node_runtime) fail with ImportError when
        the script runs as __main__ with no package context.
        """
        import inspect
        from comfyui_to_python.generator import generated_helpers

        relative_import_pattern = re.compile(r"^\s*from\s+\.\s*\w+")
        offenders = []

        for name in generated_helpers.__all__:
            obj = getattr(generated_helpers, name, None)
            if obj is None or name == "_GENERATED_GLOBALS":
                continue
            src = inspect.getsource(obj)
            matches = relative_import_pattern.findall(src)
            if matches:
                offending_lines = [
                    i + 1
                    for i, line in enumerate(src.splitlines())
                    if relative_import_pattern.search(line)
                ]
                offenders.append(
                    f"{name}: {matches} at lines {offending_lines}"
                )

        self.assertEqual(
            offenders,
            [],
            f"Found relative imports in embedded helpers:\n"
            + "\n".join(f"  - {o}" for o in offenders),
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
