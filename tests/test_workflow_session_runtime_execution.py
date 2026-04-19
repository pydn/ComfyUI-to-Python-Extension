import json
import unittest
from unittest.mock import MagicMock, patch

from comfyui_to_python.runtime_session import WorkflowSessionRuntime


class StubNode:
    """Stub node class for testing."""

    FUNCTION = "execute"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"value": ("STRING",)}}

    def execute(self, value):
        return (f"result:{value}",)


class TestWorkflowSessionRuntimeDoRun(unittest.TestCase):
    """Tests for WorkflowSessionRuntime._do_run() workflow execution."""

    @patch("comfyui_to_python.runtime_session.WorkflowSessionRuntime._do_close")
    def test_run_executes_workflow_nodes(self, mock_do_close):
        workflow_data = {
            "1": {
                "class_type": "StubNode",
                "inputs": {"value": "test"},
            }
        }
        node_mappings = {"StubNode": StubNode}
        runtime = WorkflowSessionRuntime()
        runtime._workflow_data = workflow_data
        runtime._node_class_mappings = node_mappings
        runtime.node_instances = {"StubNode": StubNode()}
        runtime._node_classes = {"StubNode": StubNode}

        result = runtime.run()

        self.assertIn("1", result)
        self.assertEqual(result["1"], ["result:test"])

    @patch(
        "comfyui_to_python.runtime_session.WorkflowSessionRuntime._ensure_node_instances"
    )
    def test_run_with_no_workflow_data_returns_none(self, mock_ensure):
        runtime = WorkflowSessionRuntime()
        result = runtime.run()
        self.assertIsNone(result)

    @patch(
        "comfyui_to_python.runtime_session.WorkflowSessionRuntime._ensure_node_instances"
    )
    def test_run_with_no_node_mappings_returns_none(self, mock_ensure):
        runtime = WorkflowSessionRuntime()
        runtime._workflow_data = {"1": {"class_type": "Test", "inputs": {}}}
        result = runtime.run()
        self.assertIsNone(result)

    @patch(
        "comfyui_to_python.runtime_session.WorkflowSessionRuntime._ensure_node_instances"
    )
    def test_run_node_not_in_mappings_is_skipped(self, mock_unknown):
        workflow_data = {
            "1": {
                "class_type": "UnknownNode",
                "inputs": {"value": "test"},
            }
        }
        node_mappings = {"StubNode": StubNode}
        runtime = WorkflowSessionRuntime()
        runtime._workflow_data = workflow_data
        runtime._node_class_mappings = node_mappings

        result = runtime.run()

        # Unknown node is skipped, but the call still returns empty dict
        # since no node instances were created
        self.assertEqual(result, {})

    def test_run_node_returns_tuple_is_converted_to_list(self):
        workflow_data = {
            "1": {
                "class_type": "StubNode",
                "inputs": {"value": "multi"},
            }
        }
        node_mappings = {"StubNode": StubNode}
        runtime = WorkflowSessionRuntime()
        runtime._workflow_data = workflow_data
        runtime._node_class_mappings = node_mappings
        runtime.node_instances = {"StubNode": StubNode()}
        runtime._node_classes = {"StubNode": StubNode}

        result = runtime.run()

        self.assertIsInstance(result["1"], list)
        self.assertEqual(result["1"][0], "result:multi")

    def test_run_preserves_extra_pnginfo(self):
        workflow_data = {
            "1": {
                "class_type": "StubNode",
                "inputs": {"value": "test"},
            }
        }
        node_mappings = {"StubNode": StubNode}
        extra_pnginfo = {"workflow": {"test": True}}
        runtime = WorkflowSessionRuntime()
        runtime._workflow_data = workflow_data
        runtime._node_class_mappings = node_mappings
        runtime._extra_pnginfo = extra_pnginfo
        runtime.node_instances = {"StubNode": StubNode()}
        runtime._node_classes = {"StubNode": StubNode}

        result = runtime.run()

        self.assertIn("1", result)

    def test_run_persists_parameters_across_calls(self):
        workflow_data = {
            "1": {
                "class_type": "StubNode",
                "inputs": {"value": "persist"},
            }
        }
        node_mappings = {"StubNode": StubNode}
        runtime = WorkflowSessionRuntime()

        with patch.object(
            runtime, "_do_run", return_value={"1": ["result:persist"]}
        ) as mock_do_run:
            runtime.run(
                workflow_data=workflow_data, node_class_mappings=node_mappings
            )
            runtime.run()

        self.assertEqual(mock_do_run.call_count, 2)

    def test_run_does_not_corrupt_session_on_exception(self):
        workflow_data = {
            "1": {
                "class_type": "StubNode",
                "inputs": {"value": "test"},
            }
        }
        node_mappings = {"StubNode": StubNode}
        runtime = WorkflowSessionRuntime()
        runtime._workflow_data = workflow_data
        runtime._node_class_mappings = node_mappings
        mock_instance = MagicMock()
        mock_instance.execute.side_effect = ValueError("boom")
        runtime.node_instances = {"StubNode": mock_instance}
        runtime._node_classes = {"StubNode": StubNode}

        with self.assertRaises(ValueError):
            runtime.run()

        # Session should still be usable
        node_mappings["StubNode"] = StubNode
        runtime.node_instances = {"StubNode": StubNode()}
        runtime._node_classes = {"StubNode": StubNode}
        result = runtime.run()
        self.assertEqual(result["1"], ["result:test"])

    @patch(
        "comfyui_to_python.runtime_session.WorkflowSessionRuntime._ensure_node_instances"
    )
    def test_run_increments_run_count(self, mock_ensure):
        workflow_data = {
            "1": {
                "class_type": "StubNode",
                "inputs": {"value": "test"},
            }
        }
        node_mappings = {"StubNode": StubNode}
        runtime = WorkflowSessionRuntime()
        runtime._workflow_data = workflow_data
        runtime._node_class_mappings = node_mappings

        runtime.run()
        self.assertEqual(runtime.run_count, 1)
        runtime.run()
        self.assertEqual(runtime.run_count, 2)

    @patch(
        "comfyui_to_python.runtime_session.WorkflowSessionRuntime._ensure_node_instances"
    )
    def test_session_policy_does_not_clear_cache(self, mock_ensure):
        workflow_data = {
            "1": {
                "class_type": "StubNode",
                "inputs": {"value": "test"},
            }
        }
        node_mappings = {"StubNode": StubNode}
        runtime = WorkflowSessionRuntime(cleanup_policy="session")
        runtime._workflow_data = workflow_data
        runtime._node_class_mappings = node_mappings

        with patch.object(runtime, "clear_runtime_cache") as mock_clear:
            runtime.run()
            mock_clear.assert_not_called()

    @patch(
        "comfyui_to_python.runtime_session.WorkflowSessionRuntime._ensure_node_instances"
    )
    def test_per_run_policy_clears_cache_after_each_run(self, mock_ensure):
        workflow_data = {
            "1": {
                "class_type": "StubNode",
                "inputs": {"value": "test"},
            }
        }
        node_mappings = {"StubNode": StubNode}
        runtime = WorkflowSessionRuntime(cleanup_policy="per_run")
        runtime._workflow_data = workflow_data
        runtime._node_class_mappings = node_mappings

        with patch.object(runtime, "clear_runtime_cache") as mock_clear:
            runtime.run()
            mock_clear.assert_called_once()

    @patch(
        "comfyui_to_python.runtime_session.WorkflowSessionRuntime._ensure_node_instances"
    )
    def test_manual_policy_never_clears_cache(self, mock_ensure):
        workflow_data = {
            "1": {
                "class_type": "StubNode",
                "inputs": {"value": "test"},
            }
        }
        node_mappings = {"StubNode": StubNode}
        runtime = WorkflowSessionRuntime(cleanup_policy="manual")
        runtime._workflow_data = workflow_data
        runtime._node_class_mappings = node_mappings

        with patch.object(runtime, "clear_runtime_cache") as mock_clear:
            runtime.run()
            runtime.run()
            mock_clear.assert_not_called()

    def test_node_instances_are_cached(self):
        workflow_data = {
            "1": {
                "class_type": "StubNode",
                "inputs": {"value": "test"},
            }
        }
        node_mappings = {"StubNode": StubNode}
        runtime = WorkflowSessionRuntime()
        runtime._workflow_data = workflow_data
        runtime._node_class_mappings = node_mappings

        with patch(
            "comfyui_to_python.runtime_session.WorkflowSessionRuntime._do_run",
            return_value={"1": ["result:test"]},
        ):
            runtime.run()
            runtime.run()

        # Node class should only be instantiated once
        self.assertIn("StubNode", runtime.node_instances)
        self.assertEqual(len(runtime.node_instances), 1)


if __name__ == "__main__":
    unittest.main()
