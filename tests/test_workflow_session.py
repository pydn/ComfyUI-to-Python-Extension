import threading
import unittest
from unittest.mock import MagicMock, patch

from comfyui_to_python import WorkflowSession


class TestWorkflowSessionInit(unittest.TestCase):
    """Tests for WorkflowSession initialization."""

    def test_init_default_cleanup_policy(self):
        session = WorkflowSession()
        self.assertEqual(session._runtime._cleanup_policy, "session")

    def test_init_accepts_per_run_policy(self):
        session = WorkflowSession(cleanup_policy="per_run")
        self.assertEqual(session._runtime._cleanup_policy, "per_run")

    def test_init_accepts_manual_policy(self):
        session = WorkflowSession(cleanup_policy="manual")
        self.assertEqual(session._runtime._cleanup_policy, "manual")

    def test_init_accepts_reset_every_n_runs(self):
        session = WorkflowSession(reset_every_n_runs=5)
        self.assertEqual(session._runtime._reset_every_n_runs, 5)

    def test_init_wraps_runtime(self):
        session = WorkflowSession()
        self.assertIsInstance(session._runtime, object)
        self.assertTrue(hasattr(session._runtime, "run"))
        self.assertTrue(hasattr(session._runtime, "close"))
        self.assertTrue(hasattr(session._runtime, "clear_runtime_cache"))


class TestWorkflowSessionRun(unittest.TestCase):
    """Tests for WorkflowSession.run() delegation."""

    @patch("comfyui_to_python.runtime_session.WorkflowSessionRuntime._do_run")
    def test_run_delegates_to_runtime(self, mock_do_run):
        mock_do_run.return_value = {"result": [1, 2, 3]}
        session = WorkflowSession()
        result = session.run()
        self.assertEqual(result, {"result": [1, 2, 3]})

    @patch("comfyui_to_python.runtime_session.WorkflowSessionRuntime._do_run")
    def test_run_with_workflow_data(self, mock_do_run):
        workflow_data = {"1": {"class_type": "TestNode", "inputs": {"x": 1}}}
        node_mappings = {"TestNode": MagicMock()}
        session = WorkflowSession()
        session.run(workflow_data=workflow_data, node_class_mappings=node_mappings)
        mock_do_run.assert_called_once()

    @patch("comfyui_to_python.runtime_session.WorkflowSessionRuntime._do_run")
    def test_run_with_extra_pnginfo(self, mock_do_run):
        extra_pnginfo = {"workflow": {"metadata": "test"}}
        session = WorkflowSession()
        session.run(extra_pnginfo=extra_pnginfo)
        mock_do_run.assert_called_once()

    @patch("comfyui_to_python.runtime_session.WorkflowSessionRuntime._do_run")
    def test_run_passes_all_parameters(self, mock_do_run):
        workflow_data = {"1": {"class_type": "TestNode", "inputs": {}}}
        node_mappings = {"TestNode": MagicMock()}
        extra_pnginfo = {"workflow": {}}
        session = WorkflowSession()
        session.run(
            workflow_data=workflow_data,
            node_class_mappings=node_mappings,
            extra_pnginfo=extra_pnginfo,
        )
        mock_do_run.assert_called_once()


class TestWorkflowSessionClose(unittest.TestCase):
    """Tests for WorkflowSession.close() delegation."""

    def test_close_delegates_to_runtime(self):
        session = WorkflowSession()
        with patch.object(session._runtime, "close") as mock_close:
            session.close(unload_models=True)
            mock_close.assert_called_once_with(unload_models=True)

    def test_close_delegates_with_unload_false(self):
        session = WorkflowSession()
        with patch.object(session._runtime, "close") as mock_close:
            session.close(unload_models=False)
            mock_close.assert_called_once_with(unload_models=False)

    def test_run_after_close_raises(self):
        session = WorkflowSession()
        session.close()
        with self.assertRaises(RuntimeError):
            session.run()


class TestWorkflowSessionClearCache(unittest.TestCase):
    """Tests for WorkflowSession.clear_runtime_cache() delegation."""

    @patch("comfyui_to_python.runtime_session.WorkflowSessionRuntime.clear_runtime_cache")
    def test_clear_cache_delegates_to_runtime(self, mock_clear):
        session = WorkflowSession()
        session.clear_runtime_cache()
        mock_clear.assert_called_once()


if __name__ == "__main__":
    unittest.main()
