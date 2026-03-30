import sys
import types
import unittest
import warnings
from unittest.mock import Mock, patch

from comfyui_to_python.node_runtime import cleanup_comfyui_runtime


class NodeRuntimeCleanupTest(unittest.TestCase):
    def test_cleanup_releases_caches_without_forcing_model_unload_by_default(self):
        comfy_module = types.ModuleType("comfy")
        comfy_module.__path__ = []
        model_management = types.ModuleType("comfy.model_management")
        model_management.cleanup_models_gc = Mock()
        model_management.unload_all_models = Mock()
        model_management.soft_empty_cache = Mock()
        comfy_module.model_management = model_management

        with patch.dict(
            sys.modules,
            {
                "comfy": comfy_module,
                "comfy.model_management": model_management,
            },
        ), patch.dict("os.environ", {}, clear=False):
            cleanup_comfyui_runtime()

        model_management.cleanup_models_gc.assert_called_once_with()
        model_management.soft_empty_cache.assert_called_once_with()
        model_management.unload_all_models.assert_not_called()

    def test_cleanup_can_force_model_unload_from_environment(self):
        comfy_module = types.ModuleType("comfy")
        comfy_module.__path__ = []
        model_management = types.ModuleType("comfy.model_management")
        model_management.cleanup_models_gc = Mock()
        model_management.unload_all_models = Mock()
        model_management.soft_empty_cache = Mock()
        comfy_module.model_management = model_management

        with patch.dict(
            sys.modules,
            {
                "comfy": comfy_module,
                "comfy.model_management": model_management,
            },
        ), patch.dict(
            "os.environ",
            {"COMFYUI_TOPYTHON_UNLOAD_MODELS": "true"},
            clear=False,
        ):
            cleanup_comfyui_runtime()

        model_management.unload_all_models.assert_called_once_with()

    def test_cleanup_suppresses_hook_failures_and_warns(self):
        comfy_module = types.ModuleType("comfy")
        comfy_module.__path__ = []
        model_management = types.ModuleType("comfy.model_management")
        model_management.cleanup_models_gc = Mock(side_effect=RuntimeError("gc failed"))
        model_management.unload_all_models = Mock(side_effect=RuntimeError("unload failed"))
        model_management.soft_empty_cache = Mock(side_effect=RuntimeError("cache failed"))
        comfy_module.model_management = model_management

        with patch.dict(
            sys.modules,
            {
                "comfy": comfy_module,
                "comfy.model_management": model_management,
            },
        ), warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            cleanup_comfyui_runtime(unload_models=True)

        model_management.cleanup_models_gc.assert_called_once_with()
        model_management.unload_all_models.assert_called_once_with()
        model_management.soft_empty_cache.assert_called_once_with()
        self.assertEqual(len(caught), 3)
        self.assertEqual(
            [str(warning.message) for warning in caught],
            [
                "ComfyUI cleanup hook cleanup_models_gc failed during teardown: gc failed",
                "ComfyUI cleanup hook unload_all_models failed during teardown: unload failed",
                "ComfyUI cleanup hook soft_empty_cache failed during teardown: cache failed",
            ],
        )

    def test_cleanup_does_not_mask_active_workflow_exception(self):
        comfy_module = types.ModuleType("comfy")
        comfy_module.__path__ = []
        model_management = types.ModuleType("comfy.model_management")
        model_management.cleanup_models_gc = Mock(side_effect=RuntimeError("cleanup failed"))
        model_management.soft_empty_cache = Mock()
        comfy_module.model_management = model_management

        with patch.dict(
            sys.modules,
            {
                "comfy": comfy_module,
                "comfy.model_management": model_management,
            },
        ), warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            with self.assertRaisesRegex(ValueError, "workflow failed"):
                try:
                    raise ValueError("workflow failed")
                finally:
                    cleanup_comfyui_runtime()

        model_management.cleanup_models_gc.assert_called_once_with()
        model_management.soft_empty_cache.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
