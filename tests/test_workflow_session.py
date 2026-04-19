import unittest
from unittest.mock import MagicMock, patch

from comfyui_to_python.runtime_session import WorkflowSession


class TestWorkflowSessionInit(unittest.TestCase):
    """Tests for WorkflowSession initialization."""

    def test_init_creates_runtime(self):
        session = WorkflowSession()
        self.assertIsNotNone(session._runtime)

    def test_init_passes_cleanup_policy(self):
        session = WorkflowSession(cleanup_policy="per_run")
        self.assertEqual(session._runtime._cleanup_policy, "per_run")

    def test_init_passes_reset_every_n_runs(self):
        session = WorkflowSession(reset_every_n_runs=5)
        self.assertEqual(session._runtime._reset_every_n_runs, 5)


class TestWorkflowSessionDelegation(unittest.TestCase):
    """Tests for WorkflowSession public API delegation to internal runtime."""

    def _make_session(self):
        return WorkflowSession()

    def test_run_delegates_to_runtime(self):
        session = self._make_session()
        workflow_data = {
            "1": {
                "class_type": "StubNode",
                "inputs": {"value": "test"},
            }
        }
        node_mappings = {"StubNode": MagicMock()}
        session._runtime.node_instances = {"StubNode": MagicMock()}
        session._runtime._node_classes = {"StubNode": MagicMock()}

        with patch.object(
            session._runtime, "run", return_value={"1": ["result"]}
        ) as mock_run:
            session.run(workflow_data=workflow_data, node_class_mappings=node_mappings)
            mock_run.assert_called_once_with(
                workflow_data=workflow_data,
                node_class_mappings=node_mappings,
                extra_pnginfo=None,
            )

    def test_clear_runtime_cache_delegates_to_runtime(self):
        session = self._make_session()
        with patch.object(
            session._runtime, "clear_runtime_cache"
        ) as mock_clear:
            session.clear_runtime_cache()
            mock_clear.assert_called_once()

    def test_close_delegates_to_runtime(self):
        session = self._make_session()
        with patch.object(
            session._runtime, "close"
        ) as mock_close:
            session.close(unload_models=True)
            mock_close.assert_called_once_with(unload_models=True)

    def test_run_raises_after_close(self):
        session = self._make_session()
        session.close()
        with self.assertRaises(RuntimeError):
            session.run()


if __name__ == "__main__":
    unittest.main()
