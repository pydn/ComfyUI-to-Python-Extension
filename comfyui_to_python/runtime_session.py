import gc
import json
import threading
from typing import Any, Literal

from comfyui_to_python.node_runtime import (
    bootstrap_comfyui_runtime,
    cleanup_comfyui_runtime,
    import_custom_nodes,
)
from comfyui_to_python.generator.model import GenerationPlan


_CLEANUP_POLICIES = {"per_run", "session", "manual"}


class WorkflowSessionRuntime:
    """Internal runtime session for warm reuse of ComfyUI state."""

    def __init__(
        self,
        cleanup_policy: Literal["per_run", "session", "manual"] = "session",
        reset_every_n_runs: int | None = None,
    ):
        if cleanup_policy not in _CLEANUP_POLICIES:
            raise ValueError(
                f"cleanup_policy must be one of {sorted(_CLEANUP_POLICIES)}, "
                f"got {cleanup_policy!r}"
            )

        self._cleanup_policy: Literal["per_run", "session", "manual"] = cleanup_policy
        self._reset_every_n_runs: int | None = reset_every_n_runs

        self.bootstrapped: bool = False
        self.custom_nodes_initialized: bool = False
        self.node_instances: dict[str, Any] = {}
        self._node_classes: dict[str, Any] = {}
        self.run_count: int = 0
        self._closed: bool = False
        self._lock: threading.Lock = threading.Lock()
        self._workflow_data: dict | None = None
        self._node_class_mappings: dict | None = None
        self._extra_pnginfo: dict | None = None

    def _ensure_bootstrapped(self) -> None:
        if self.bootstrapped:
            return
        bootstrap_comfyui_runtime()
        self.bootstrapped = True

    def _ensure_custom_nodes_initialized(self) -> None:
        if self.custom_nodes_initialized:
            return
        import_custom_nodes()
        self.custom_nodes_initialized = True

    def _ensure_node_instances(self, node_classes: dict) -> None:
        for class_type, node_class in node_classes.items():
            if class_type in self.node_instances:
                continue
            self.node_instances[class_type] = node_class()
            self._node_classes[class_type] = node_class

    def clear_runtime_cache(self) -> None:
        if self._cleanup_policy == "session":
            return
        if self._cleanup_policy == "per_run":
            cleanup_comfyui_runtime(unload_models=True)

    def close(self, unload_models: bool = True) -> None:
        if self._closed:
            return
        self._do_close(unload_models=unload_models)
        self._closed = True

    def _do_close(self, unload_models: bool = True) -> None:
        cleanup_comfyui_runtime(unload_models=unload_models)
        gc.collect()

    def _do_run(self) -> Any:
        if not self._workflow_data or not self._node_class_mappings:
            return None

        prompt = json.loads(json.dumps(self._workflow_data))
        extra_pnginfo = self._extra_pnginfo if hasattr(self, "_extra_pnginfo") else None

        try:
            import torch

            inference_ctx = torch.inference_mode
        except ImportError:

            def inference_ctx():
                class _DummyCtx:
                    def __enter__(self):
                        pass

                    def __exit__(self, *args):
                        pass

                return _DummyCtx()

        with inference_ctx():
            outputs = {}
            for node_id, node in prompt.items():
                class_type = node.get("class_type", "")
                inputs = node.get("inputs", {})
                if class_type not in self.node_instances:
                    continue
                node_instance = self.node_instances[class_type]
                node_class = self._node_classes.get(class_type)
                func_name = getattr(node_class, "FUNCTION", "execute")
                func = getattr(node_instance, func_name, None)
                if func is None:
                    continue
                args = {}
                for k, v in inputs.items():
                    args[k] = v
                result = func(**args)
                if isinstance(result, tuple) or isinstance(result, list):
                    outputs[node_id] = list(result)
                else:
                    outputs[node_id] = result

        return outputs

    def run(
        self,
        workflow_data: dict | None = None,
        node_class_mappings: dict | None = None,
        extra_pnginfo: dict | None = None,
    ) -> Any:
        with self._lock:
            if self._closed:
                raise RuntimeError(
                    "Cannot run() on a closed WorkflowSessionRuntime"
                )

            self._workflow_data = workflow_data or self._workflow_data
            self._node_class_mappings = (
                node_class_mappings or self._node_class_mappings
            )
            self._extra_pnginfo = extra_pnginfo or self._extra_pnginfo

            if self._node_class_mappings:
                self._ensure_node_instances(self._node_class_mappings)

            try:
                result = self._do_run()
            except Exception:
                raise
            else:
                if self._cleanup_policy == "per_run":
                    self.clear_runtime_cache()
                self.run_count += 1

                if (
                    self._reset_every_n_runs
                    and self.run_count % self._reset_every_n_runs == 0
                ):
                    self._do_close(unload_models=False)
                    self._closed = False
                    self.bootstrapped = False
                    self.custom_nodes_initialized = False
                    self.node_instances.clear()
                    self._node_classes.clear()
                    self.run_count = 0

                return result


class WorkflowSession:
    """A reusable warm-session wrapper for generated ComfyUI workflows.

    This is the public API class that wraps WorkflowSessionRuntime.
    It delegates all method calls to the internal runtime instance.
    """

    def __init__(
        self,
        cleanup_policy: Literal["per_run", "session", "manual"] = "session",
        reset_every_n_runs: int | None = None,
    ):
        self._runtime = WorkflowSessionRuntime(
            cleanup_policy=cleanup_policy,
            reset_every_n_runs=reset_every_n_runs,
        )

    def run(
        self,
        workflow_data: dict | None = None,
        node_class_mappings: dict | None = None,
        extra_pnginfo: dict | None = None,
    ) -> Any:
        return self._runtime.run(
            workflow_data=workflow_data,
            node_class_mappings=node_class_mappings,
            extra_pnginfo=extra_pnginfo,
        )

    def clear_runtime_cache(self) -> None:
        self._runtime.clear_runtime_cache()

    def close(self, unload_models: bool = True) -> None:
        self._runtime.close(unload_models=unload_models)
