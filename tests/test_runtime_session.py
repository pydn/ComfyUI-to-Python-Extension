import threading
import unittest
from unittest.mock import MagicMock, patch, call

from comfyui_to_python.runtime_session import WorkflowSessionRuntime


class TestWorkflowSessionRuntimeInit(unittest.TestCase):
    """Tests for WorkflowSessionRuntime initialization."""

    def test_init_default_cleanup_policy_is_session(self):
        runtime = WorkflowSessionRuntime()
        self.assertEqual(runtime._cleanup_policy, "session")

    def test_init_accepts_per_run_policy(self):
        runtime = WorkflowSessionRuntime(cleanup_policy="per_run")
        self.assertEqual(runtime._cleanup_policy, "per_run")

    def test_init_accepts_manual_policy(self):
        runtime = WorkflowSessionRuntime(cleanup_policy="manual")
        self.assertEqual(runtime._cleanup_policy, "manual")

    def test_init_rejects_invalid_policy(self):
        with self.assertRaises(ValueError):
            WorkflowSessionRuntime(cleanup_policy="invalid")

    def test_init_sets_default_reset_every_n_runs_none(self):
        runtime = WorkflowSessionRuntime()
        self.assertIsNone(runtime._reset_every_n_runs)

    def test_init_accepts_reset_every_n_runs(self):
        runtime = WorkflowSessionRuntime(reset_every_n_runs=5)
        self.assertEqual(runtime._reset_every_n_runs, 5)

    def test_init_has_lock(self):
        runtime = WorkflowSessionRuntime()
        self.assertIsInstance(runtime._lock, type(threading.Lock()))

    def test_init_bootstrapped_false(self):
        runtime = WorkflowSessionRuntime()
        self.assertFalse(runtime.bootstrapped)

    def test_init_custom_nodes_initialized_false(self):
        runtime = WorkflowSessionRuntime()
        self.assertFalse(runtime.custom_nodes_initialized)

    def test_init_run_count_zero(self):
        runtime = WorkflowSessionRuntime()
        self.assertEqual(runtime.run_count, 0)

    def test_init_closed_false(self):
        runtime = WorkflowSessionRuntime()
        self.assertFalse(runtime._closed)


class TestWorkflowSessionRuntimeLifecycle(unittest.TestCase):
    """Tests for WorkflowSessionRuntime lifecycle management."""

    def _make_runtime(self):
        return WorkflowSessionRuntime()

    @patch("comfyui_to_python.runtime_session.bootstrap_comfyui_runtime")
    def test_ensure_bootstrapped_calls_bootstrap_once(self, mock_bootstrap):
        runtime = self._make_runtime()
        runtime._ensure_bootstrapped()
        mock_bootstrap.assert_called_once()
        self.assertTrue(runtime.bootstrapped)

    @patch("comfyui_to_python.runtime_session.bootstrap_comfyui_runtime")
    def test_ensure_bootstrapped_skips_if_already_bootstrapped(self, mock_bootstrap):
        runtime = self._make_runtime()
        runtime._ensure_bootstrapped()
        runtime._ensure_bootstrapped()
        self.assertEqual(mock_bootstrap.call_count, 1)

    @patch("comfyui_to_python.runtime_session.import_custom_nodes")
    def test_ensure_custom_nodes_init_calls_import_once(self, mock_import):
        runtime = self._make_runtime()
        runtime._ensure_custom_nodes_initialized()
        mock_import.assert_called_once()
        self.assertTrue(runtime.custom_nodes_initialized)

    @patch("comfyui_to_python.runtime_session.import_custom_nodes")
    def test_ensure_custom_nodes_init_skips_if_already_initialized(self, mock_import):
        runtime = self._make_runtime()
        runtime._ensure_custom_nodes_initialized()
        runtime._ensure_custom_nodes_initialized()
        self.assertEqual(mock_import.call_count, 1)

    def test_close_sets_closed_flag(self):
        runtime = self._make_runtime()
        runtime.close(unload_models=True)
        self.assertTrue(runtime._closed)

    def test_close_is_idempotent(self):
        runtime = self._make_runtime()
        with patch.object(runtime, "_do_close") as mock_do_close:
            runtime.close(unload_models=True)
            runtime.close(unload_models=True)
            self.assertEqual(mock_do_close.call_count, 1)


class TestWorkflowSessionRuntimeRunCount(unittest.TestCase):
    """Tests for run count tracking."""

    def _make_runtime(self):
        return WorkflowSessionRuntime()

    @patch("comfyui_to_python.runtime_session.WorkflowSessionRuntime._do_run")
    def test_run_increments_run_count(self, mock_do_run):
        runtime = self._make_runtime()
        mock_do_run.return_value = {"result": [1]}
        runtime.run()
        self.assertEqual(runtime.run_count, 1)
        runtime.run()
        self.assertEqual(runtime.run_count, 2)


class TestWorkflowSessionRuntimeExceptionSafety(unittest.TestCase):
    """Tests that exceptions during run() do not corrupt session state."""

    def _make_runtime(self):
        return WorkflowSessionRuntime()

    @patch("comfyui_to_python.runtime_session.WorkflowSessionRuntime._do_run")
    def test_exception_does_not_clear_bootstrapped(self, mock_do_run):
        runtime = self._make_runtime()
        runtime.bootstrapped = True
        mock_do_run.side_effect = RuntimeError("simulated failure")
        with self.assertRaises(RuntimeError):
            runtime.run()
        self.assertTrue(runtime.bootstrapped)

    @patch("comfyui_to_python.runtime_session.WorkflowSessionRuntime._do_run")
    def test_exception_preserves_custom_nodes_initialized(self, mock_do_run):
        runtime = self._make_runtime()
        runtime.custom_nodes_initialized = True
        mock_do_run.side_effect = RuntimeError("simulated failure")
        with self.assertRaises(RuntimeError):
            runtime.run()
        self.assertTrue(runtime.custom_nodes_initialized)

    @patch("comfyui_to_python.runtime_session.WorkflowSessionRuntime._do_run")
    def test_run_count_not_incremented_on_exception(self, mock_do_run):
        runtime = self._make_runtime()
        mock_do_run.side_effect = RuntimeError("simulated failure")
        with self.assertRaises(RuntimeError):
            runtime.run()
        self.assertEqual(runtime.run_count, 0)


class TestWorkflowSessionRuntimeAlreadyClosed(unittest.TestCase):
    """Tests for behavior after close()."""

    def _make_runtime(self):
        return WorkflowSessionRuntime()

    def test_run_after_close_raises(self):
        runtime = self._make_runtime()
        runtime.close()
        with self.assertRaises(RuntimeError):
            runtime.run()


class TestWorkflowSessionRuntimeNodeInstances(unittest.TestCase):
    """Tests for cached node instance management."""

    def _make_runtime(self):
        return WorkflowSessionRuntime()

    def test_ensure_node_instances_caches_instances(self):
        runtime = self._make_runtime()
        node_class = MagicMock()
        runtime._ensure_node_instances({"TestNode": node_class})
        self.assertIn("TestNode", runtime.node_instances)

    def test_ensure_node_instances_creates_instance(self):
        runtime = self._make_runtime()
        node_class = MagicMock()
        runtime._ensure_node_instances({"TestNode": node_class})
        node_class.assert_called_once()

    def test_ensure_node_instances_reuses_cached(self):
        runtime = self._make_runtime()
        node_class = MagicMock()
        runtime._ensure_node_instances({"TestNode": node_class})
        runtime._ensure_node_instances({"TestNode": node_class})
        node_class.assert_called_once()


class TestWorkflowSessionRuntimeClearRuntimeCache(unittest.TestCase):
    """Tests for clear_runtime_cache behavior."""

    def _make_runtime(self):
        return WorkflowSessionRuntime()

    @patch("comfyui_to_python.runtime_session.cleanup_comfyui_runtime")
    def test_clear_runtime_cache_session_policy_skips_unload(self, mock_cleanup):
        runtime = WorkflowSessionRuntime(cleanup_policy="session")
        runtime.bootstrapped = True
        runtime.clear_runtime_cache()
        # session policy should NOT call unload_all_models
        mock_cleanup.assert_not_called()

    @patch("comfyui_to_python.runtime_session.cleanup_comfyui_runtime")
    def test_clear_runtime_cache_per_run_policy_calls_full_cleanup(self, mock_cleanup):
        runtime = WorkflowSessionRuntime(cleanup_policy="per_run")
        runtime.bootstrapped = True
        runtime.clear_runtime_cache()
        mock_cleanup.assert_called_once_with(unload_models=True)

    @patch("comfyui_to_python.runtime_session.cleanup_comfyui_runtime")
    def test_clear_runtime_cache_manual_policy_no_cleanup(self, mock_cleanup):
        runtime = WorkflowSessionRuntime(cleanup_policy="manual")
        runtime.bootstrapped = True
        runtime.clear_runtime_cache()
        mock_cleanup.assert_not_called()


class TestWorkflowSessionRuntimeDoClose(unittest.TestCase):
    """Tests for _do_close internal method."""

    def _make_runtime(self):
        return WorkflowSessionRuntime()

    @patch("comfyui_to_python.runtime_session.cleanup_comfyui_runtime")
    @patch("comfyui_to_python.runtime_session.gc")
    def test_do_close_calls_cleanup_with_unload(self, mock_gc, mock_cleanup):
        runtime = self._make_runtime()
        runtime._do_close(unload_models=True)
        mock_cleanup.assert_called_once_with(unload_models=True)

    @patch("comfyui_to_python.runtime_session.cleanup_comfyui_runtime")
    @patch("comfyui_to_python.runtime_session.gc")
    def test_do_close_calls_cleanup_without_unload(self, mock_gc, mock_cleanup):
        runtime = self._make_runtime()
        runtime._do_close(unload_models=False)
        mock_cleanup.assert_called_once_with(unload_models=False)


if __name__ == "__main__":
    unittest.main()
