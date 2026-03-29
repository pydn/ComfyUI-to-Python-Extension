import sys
import types
import unittest
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


if __name__ == "__main__":
    unittest.main()
