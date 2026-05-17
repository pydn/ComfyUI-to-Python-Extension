"""Tests for renderer readability helpers."""

import unittest

from comfyui_to_python.generator.model import GenerationPlan
from comfyui_to_python.generator.render import WorkflowRenderer


class WorkflowRendererReadabilityTest(unittest.TestCase):
    def test_renderer_exposes_named_section_builders(self):
        renderer = WorkflowRenderer()
        plan = GenerationPlan(
            workflow_data={"1": {"class_type": "Example", "inputs": {}}},
            metadata_workflow_data=None,
            custom_nodes=False,
            import_statements={},
            special_functions_code=[],
            loop_code=[],
            queue_size=1,
        )

        static_imports = renderer._build_static_imports(plan)
        workflow_section = renderer._build_workflow_section(plan)
        execution_section = renderer._build_execution_section(plan)
        entrypoint_section = renderer._build_entrypoint_section()

        self.assertIn("# Imports", static_imports)
        self.assertIn("def build_workflow()", "\n".join(workflow_section))
        self.assertIn("def main", "\n".join(execution_section))
        self.assertEqual(entrypoint_section[-1], "    main()")


if __name__ == "__main__":
    unittest.main()
