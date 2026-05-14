"""Tests for ExportApplication base_node_class_mappings behavior.

Verifies that after custom node import, base_node_class_mappings retains the
pre-custom-node baseline so WorkflowPlanner correctly distinguishes between
built-in nodes (direct import) and custom/extras nodes (NODE_CLASS_MAPPINGS lookup).
"""

import sys
import unittest
from io import StringIO


def _make_workflow():
    """Minimal workflow JSON string for testing."""
    return '{"1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "test.safetensors"}}}'


class TestBaseNodeClassMappings(unittest.TestCase):
    """Tests for base_node_class_mappings stability across custom node reloads."""

    def tearDown(self):
        # Clean up any sys.modules pollution to avoid cross-test contamination
        if "nodes" in sys.modules:
            del sys.modules["nodes"]

    def test_base_mappings_unchanged_after_custom_node_import(self):
        """Given custom nodes are loaded, base_node_class_mappings stays at original baseline."""
        from comfyui_to_python.app import ExportApplication

        class FakeNode:
            CATEGORY = "loaders"
            FUNCTION = "execute"

            @staticmethod
            def INPUT_TYPES():
                return {"required": {"ckpt_name": ("STRING",)}}

            def execute(self, ckpt_name: str):
                return ({},)

        class FakeCustomNode:
            CATEGORY = "custom"
            FUNCTION = "execute"

            @staticmethod
            def INPUT_TYPES():
                return {"required": {"ckpt_name": ("STRING",)}}

            def execute(self, ckpt_name: str):
                return ({},)

        initial_mappings = {"CheckpointLoaderSimple": FakeNode}
        after_import_mappings = dict(initial_mappings)
        # Simulate custom nodes adding a new class
        after_import_mappings["CustomNode"] = FakeCustomNode

        call_count = [0]

        def mock_node_loader():
            return initial_mappings

        def mock_custom_node_importer():
            call_count[0] += 1
            # Simulate populating sys.modules["nodes"].NODE_CLASS_MAPPINGS
            nodes_mod_type = type("NodesModule", (), {})()
            nodes_mod_type.NODE_CLASS_MAPPINGS = after_import_mappings
            sys.modules["nodes"] = nodes_mod_type

        output = StringIO()
        app = ExportApplication(
            workflow=_make_workflow(),
            output_file=output,
            node_mapping_loader=mock_node_loader,
            custom_node_importer=mock_custom_node_importer,
            needs_init_custom_nodes=True,
        )

        # base_node_class_mappings should be a deep copy of initial (pre-custom-node) state
        self.assertEqual(app.base_node_class_mappings, initial_mappings)
        app.execute()

        # After execute(), base_node_class_mappings must still be the original baseline
        # (not overwritten with after_import_mappings which includes custom nodes)
        self.assertEqual(
            app.base_node_class_mappings,
            initial_mappings,
            "base_node_class_mappings should remain at pre-custom-node baseline",
        )

    def test_base_mappings_is_deep_copy_not_shared_reference(self):
        """Given node mappings change in-place, base_node_class_mappings is independent."""
        from comfyui_to_python.app import ExportApplication

        class FakeNode2:
            CATEGORY = "loaders"
            FUNCTION = "execute"

            @staticmethod
            def INPUT_TYPES():
                return {"required": {"ckpt_name": ("STRING",)}}

            def execute(self, ckpt_name: str):
                return ({},)

        initial_mappings = {"CheckpointLoaderSimple": FakeNode2}

        def mock_node_loader():
            return dict(initial_mappings)

        output = StringIO()
        app = ExportApplication(
            workflow=_make_workflow(),
            output_file=output,
            node_mapping_loader=mock_node_loader,
            custom_node_importer=lambda: None,
        )

        # Mutate the live mappings
        app.node_class_mappings["NewKey"] = "value"

        # base_node_class_mappings must not reflect the mutation (deep copy)
        self.assertNotIn(
            "NewKey",
            app.base_node_class_mappings,
            "base_node_class_mappings must be a deep copy, not shared reference",
        )


class TestRenderHardenedImports(unittest.TestCase):
    """Integration test: render output contains hardened _load_module pattern."""

    def test_generated_output_contains_exec_failure_cleanup(self):
        """Given a GenerationPlan, rendered output includes try/except BaseException around exec_module()."""
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

        # The _load_module in rendered output must have the exec failure cleanup pattern
        self.assertIn("try:", generated)
        self.assertIn("spec.loader.exec_module(mod)", generated)
        self.assertIn(
            "except BaseException",
            generated,
            "Must catch BaseException for edge-case safety",
        )
        self.assertIn(
            "sys.modules.pop(module_name, None)",
            generated,
            "Must clean up sys.modules on exec failure",
        )


if __name__ == "__main__":
    unittest.main()
