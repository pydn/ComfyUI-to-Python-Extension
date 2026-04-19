import json
import unittest
from io import StringIO

from comfyui_to_python import ComfyUItoPython


class DummyNode:
    CATEGORY = "test"
    FUNCTION = "execute"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"value": ("STRING",)}}

    def execute(self, value):
        return (f"result:{value}",)


class ExportSessionModeTest(unittest.TestCase):
    """Tests for session mode export pipeline."""

    def test_comfyui_to_python_passes_execution_mode(self):
        workflow = {
            "1": {
                "class_type": "DummyNode",
                "inputs": {"value": "test"},
            }
        }

        output = StringIO()
        ComfyUItoPython(
            workflow=json.dumps(workflow),
            output_file=output,
            node_class_mappings={"DummyNode": DummyNode},
            execution_mode="session",
        )

        generated = output.getvalue()

        self.assertIn("class WorkflowSession:", generated)
        self.assertIn("def run(self)", generated)
        self.assertIn("def close(self, unload_models:", generated)

    def test_session_mode_includes_backward_compat_main(self):
        workflow = {
            "1": {
                "class_type": "DummyNode",
                "inputs": {"value": "test"},
            }
        }

        output = StringIO()
        ComfyUItoPython(
            workflow=json.dumps(workflow),
            output_file=output,
            node_class_mappings={"DummyNode": DummyNode},
            execution_mode="session",
        )

        generated = output.getvalue()

        self.assertIn("def main(", generated)
        self.assertIn("WorkflowSession(", generated)
        self.assertIn('cleanup_policy="per_run"', generated)
        self.assertIn("if __name__ == \"__main__\":", generated)

    def test_oneshot_mode_excludes_session_class(self):
        workflow = {
            "1": {
                "class_type": "DummyNode",
                "inputs": {"value": "test"},
            }
        }

        output = StringIO()
        ComfyUItoPython(
            workflow=json.dumps(workflow),
            output_file=output,
            node_class_mappings={"DummyNode": DummyNode},
            execution_mode="oneshot",
        )

        generated = output.getvalue()

        self.assertNotIn("class WorkflowSession:", generated)

    def test_default_mode_is_oneshot(self):
        workflow = {
            "1": {
                "class_type": "DummyNode",
                "inputs": {"value": "test"},
            }
        }

        output = StringIO()
        ComfyUItoPython(
            workflow=json.dumps(workflow),
            output_file=output,
            node_class_mappings={"DummyNode": DummyNode},
        )

        generated = output.getvalue()

        self.assertNotIn("class WorkflowSession:", generated)


if __name__ == "__main__":
    unittest.main()
