import json
import unittest
from io import StringIO
from unittest.mock import patch

from comfyui_to_python import ComfyUItoPython


class LoadImage:
    CATEGORY = "image"
    FUNCTION = "load_image"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"image": ("STRING",)}}

    def load_image(self, image):
        return (image,)


class SessionRendererTest(unittest.TestCase):
    """Tests for session mode code generation in the renderer."""

    def test_session_mode_generates_workflow_session_class(self):
        workflow = {
            "1": {
                "class_type": "LoadImage",
                "inputs": {"image": "example.png"},
            }
        }

        output = StringIO()
        ComfyUItoPython(
            workflow=json.dumps(workflow),
            output_file=output,
            node_class_mappings={"LoadImage": LoadImage},
            execution_mode="session",
        )

        generated = output.getvalue()
        self.assertIn("class WorkflowSession", generated)

    def test_session_mode_generates_main_wrapper(self):
        workflow = {
            "1": {
                "class_type": "LoadImage",
                "inputs": {"image": "example.png"},
            }
        }

        output = StringIO()
        ComfyUItoPython(
            workflow=json.dumps(workflow),
            output_file=output,
            node_class_mappings={"LoadImage": LoadImage},
            execution_mode="session",
        )

        generated = output.getvalue()
        self.assertIn("def main(unload_models: bool | None = None)", generated)
        self.assertIn("WorkflowSession(", generated)

    def test_session_mode_main_creates_session_with_per_run_policy(self):
        workflow = {
            "1": {
                "class_type": "LoadImage",
                "inputs": {"image": "example.png"},
            }
        }

        output = StringIO()
        ComfyUItoPython(
            workflow=json.dumps(workflow),
            output_file=output,
            node_class_mappings={"LoadImage": LoadImage},
            execution_mode="session",
        )

        generated = output.getvalue()
        self.assertIn('cleanup_policy="per_run"', generated)

    def test_session_mode_main_has_try_finally_close(self):
        workflow = {
            "1": {
                "class_type": "LoadImage",
                "inputs": {"image": "example.png"},
            }
        }

        output = StringIO()
        ComfyUItoPython(
            workflow=json.dumps(workflow),
            output_file=output,
            node_class_mappings={"LoadImage": LoadImage},
            execution_mode="session",
        )

        generated = output.getvalue()
        self.assertIn("try:", generated)
        self.assertIn("session.run()", generated)
        self.assertIn("finally:", generated)
        self.assertIn("session.close(", generated)

    def test_session_mode_generates_run_method(self):
        workflow = {
            "1": {
                "class_type": "LoadImage",
                "inputs": {"image": "example.png"},
            }
        }

        output = StringIO()
        ComfyUItoPython(
            workflow=json.dumps(workflow),
            output_file=output,
            node_class_mappings={"LoadImage": LoadImage},
            execution_mode="session",
        )

        generated = output.getvalue()
        self.assertIn("def run(self", generated)

    def test_session_mode_generates_close_method(self):
        workflow = {
            "1": {
                "class_type": "LoadImage",
                "inputs": {"image": "example.png"},
            }
        }

        output = StringIO()
        ComfyUItoPython(
            workflow=json.dumps(workflow),
            output_file=output,
            node_class_mappings={"LoadImage": LoadImage},
            execution_mode="session",
        )

        generated = output.getvalue()
        self.assertIn("def close(self, unload_models: bool = True)", generated)

    def test_session_mode_oneshot_generates_same_code(self):
        workflow = {
            "1": {
                "class_type": "LoadImage",
                "inputs": {"image": "example.png"},
            }
        }

        output = StringIO()
        ComfyUItoPython(
            workflow=json.dumps(workflow),
            output_file=output,
            node_class_mappings={"LoadImage": LoadImage},
            execution_mode="oneshot",
        )

        generated = output.getvalue()
        self.assertNotIn("class WorkflowSession", generated)
        self.assertIn("def main(unload_models: bool | None = None)", generated)
        self.assertIn("bootstrap_comfyui_runtime()", generated)
        self.assertIn("cleanup_comfyui_runtime(unload_models=unload_models)", generated)

    def test_session_mode_oneshot_default(self):
        workflow = {
            "1": {
                "class_type": "LoadImage",
                "inputs": {"image": "example.png"},
            }
        }

        output = StringIO()
        ComfyUItoPython(
            workflow=json.dumps(workflow),
            output_file=output,
            node_class_mappings={"LoadImage": LoadImage},
        )

        generated = output.getvalue()
        self.assertNotIn("class WorkflowSession", generated)
        self.assertIn("def main(unload_models: bool | None = None)", generated)

    def test_session_mode_script_is_executable(self):
        workflow = {
            "1": {
                "class_type": "LoadImage",
                "inputs": {"image": "example.png"},
            }
        }

        output = StringIO()
        ComfyUItoPython(
            workflow=json.dumps(workflow),
            output_file=output,
            node_class_mappings={"LoadImage": LoadImage},
            execution_mode="session",
        )

        generated = output.getvalue()

        # Should not raise — checks that generated code has valid syntax
        compile(generated, "<generated>", "exec")

        # main() should be callable
        globals_dict = {"__name__": "generated_workflow_module"}
        with patch("comfyui_to_python.runtime_session.WorkflowSessionRuntime"):
            exec(generated, globals_dict)
        self.assertIn("WorkflowSession", globals_dict)
        self.assertIn("main", globals_dict)
        self.assertTrue(callable(globals_dict["main"]))

    def test_session_mode_generates_workflow_literal(self):
        workflow = {
            "1": {
                "class_type": "LoadImage",
                "inputs": {"image": "example.png"},
            }
        }

        output = StringIO()
        ComfyUItoPython(
            workflow=json.dumps(workflow),
            output_file=output,
            node_class_mappings={"LoadImage": LoadImage},
            execution_mode="session",
        )

        generated = output.getvalue()
        self.assertIn("def build_workflow()", generated)
        self.assertIn('return', generated)
        self.assertIn('"class_type": "LoadImage"', generated)

    def test_session_mode_generates_bootstrap_helper(self):
        workflow = {
            "1": {
                "class_type": "LoadImage",
                "inputs": {"image": "example.png"},
            }
        }

        output = StringIO()
        ComfyUItoPython(
            workflow=json.dumps(workflow),
            output_file=output,
            node_class_mappings={"LoadImage": LoadImage},
            execution_mode="session",
        )

        generated = output.getvalue()
        self.assertIn("def bootstrap_comfyui_runtime()", generated)

    def test_session_mode_generates_cleanup_helper(self):
        workflow = {
            "1": {
                "class_type": "LoadImage",
                "inputs": {"image": "example.png"},
            }
        }

        output = StringIO()
        ComfyUItoPython(
            workflow=json.dumps(workflow),
            output_file=output,
            node_class_mappings={"LoadImage": LoadImage},
            execution_mode="session",
        )

        generated = output.getvalue()
        self.assertIn("def cleanup_comfyui_runtime(", generated)


if __name__ == "__main__":
    unittest.main()
