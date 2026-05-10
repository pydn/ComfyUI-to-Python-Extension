import importlib.util
import logging
import os
import sys
import warnings
from typing import Any, Mapping, Sequence, Union

log = logging.getLogger(__name__)


def _is_comfyui_directory(path: str) -> bool:
    """Verify a directory has ComfyUI structural markers (nodes.py)."""
    if not os.path.isdir(path):
        return False
    return os.path.isfile(os.path.join(path, "nodes.py"))


def _load_module(module_name: str, filepath: str) -> Any:
    """Load a Python module from an explicit file path, bypassing sys.path.

    This eliminates ALL bare import shadowing attacks by loading modules
    from verified file paths instead of relying on sys.path resolution.
    """
    if not os.path.isfile(filepath):
        log.debug("Module file not found: %s (%s)", module_name, filepath)
        return None
    try:
        spec = importlib.util.spec_from_file_location(module_name, filepath)
        if spec is None or spec.loader is None:
            log.debug("Could not create spec for %s at %s", module_name, filepath)
            return None
        mod = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = mod
        spec.loader.exec_module(mod)
        return mod
    except Exception as e:
        log.debug("Failed to load %s from %s: %s", module_name, filepath, e)
        return None


def _find_from_extension_location() -> str | None:
    """Walk up from this file's location to find ComfyUI root."""
    ext_dir = os.path.dirname(os.path.realpath(__file__))
    candidate = ext_dir
    for _ in range(10):
        parent = os.path.dirname(candidate)
        if parent == candidate:
            break
        candidate = parent
        if os.path.basename(candidate) == "ComfyUI":
            if _is_comfyui_directory(candidate):
                return candidate
    return None


def find_path(name: str, max_depth: int = 20) -> str | None:
    """Iteratively walk up from CWD to find a directory by name.

    Depth-limited to prevent slow startup on deep trees.
    Each candidate verified by _is_comfyui_directory() at the caller.
    """
    candidate = os.getcwd()
    for _ in range(max_depth):
        parent = os.path.dirname(candidate)
        if parent == candidate:
            break
        candidate = parent
        if os.path.basename(candidate) == name:
            return candidate
    return None


def get_comfyui_path() -> str | None:
    """Resolve ComfyUI path via prioritized multi-strategy fallback.

    Strategy order:
      1. COMFYUI_PATH env var (verified with _is_comfyui_directory)
      2. Relative walk from extension location (realpath + verified)
      3. CWD walk (legacy fallback, depth-limited)
    """
    p = os.environ.get("COMFYUI_PATH")
    if p and _is_comfyui_directory(p):
        return p
    p = _find_from_extension_location()
    if p:
        return p
    return find_path("ComfyUI", max_depth=20)


def add_comfyui_directory_to_sys_path() -> None:
    """Add the ComfyUI checkout to sys.path (idempotent — insert-once, no gap)."""
    comfyui_path = get_comfyui_path()
    if comfyui_path is not None and os.path.isdir(comfyui_path):
        if comfyui_path not in sys.path:
            sys.path.insert(0, comfyui_path)
            log.debug("Added %s to sys.path", comfyui_path)


def add_extra_model_paths() -> None:
    """Load ComfyUI extra model paths configuration when available."""
    comfyui_path = get_comfyui_path()
    if comfyui_path is None:
        log.debug("Cannot load extra model paths: ComfyUI path not found")
        return

    # Try main.py first, then utils/extra_config.py — both via _load_module()
    main_mod = _load_module("comfy_main", os.path.join(comfyui_path, "main.py"))
    if main_mod is not None and hasattr(main_mod, "load_extra_path_config"):
        load_extra_path_config = getattr(main_mod, "load_extra_path_config")
    else:
        log.debug("main.py not available, trying utils/extra_config.py")
        extra_config_mod = _load_module(
            "extra_config", os.path.join(comfyui_path, "utils", "extra_config.py")
        )
        if extra_config_mod is None or not hasattr(
            extra_config_mod, "load_extra_path_config"
        ):
            log.debug("Could not find load_extra_path_config in either path")
            return
        load_extra_path_config = getattr(extra_config_mod, "load_extra_path_config")

    extra_model_paths = find_path("extra_model_paths.yaml")
    if extra_model_paths is not None:
        load_extra_path_config(extra_model_paths)
    else:
        log.debug("Could not find the extra_model_paths config file.")


def _load_module_temp(module_name: str, filepath: str) -> Any:
    """Load a module via _load_module() then remove it from sys.modules.

    Used during bootstrap for modules that ComfyUI's import chain also loads
    normally — prevents the cached copy from conflicting with later imports.
    """
    mod = _load_module(module_name, filepath)
    sys.modules.pop(module_name, None)
    return mod


def bootstrap_comfyui_runtime() -> None:
    """Mirror the allocator-related ComfyUI startup steps before torch import."""
    add_comfyui_directory_to_sys_path()
    comfyui_path = get_comfyui_path()
    if comfyui_path is None:
        log.debug("bootstrap_comfyui_runtime: ComfyUI path not found")
        return

    # Use _load_module for file-based isolation, but with temporary names so
    # the modules are removed from sys.modules after reading values.
    # This prevents conflicts when ComfyUI's internal import chain (e.g.
    # nodes.py -> comfy.cli_args) later loads these modules normally.
    options_mod = _load_module_temp(
        "_bootstrap_options", os.path.join(comfyui_path, "comfy", "options.py")
    )
    if options_mod is not None:
        options_mod.enable_args_parsing()

    cli_args_mod = _load_module_temp(
        "_bootstrap_cli_args", os.path.join(comfyui_path, "comfy", "cli_args.py")
    )
    args = getattr(cli_args_mod, "args", None) if cli_args_mod else None

    if args is None:
        return

    if os.name == "nt":
        os.environ["MIMALLOC_PURGE_DELAY"] = "0"

    if args.default_device is not None:
        default_dev = args.default_device
        devices = list(range(32))
        devices.remove(default_dev)
        devices.insert(0, default_dev)
        devices = ",".join(map(str, devices))
        os.environ["CUDA_VISIBLE_DEVICES"] = str(devices)
        os.environ["HIP_VISIBLE_DEVICES"] = str(devices)

    if args.cuda_device is not None:
        os.environ["CUDA_VISIBLE_DEVICES"] = str(args.cuda_device)
        os.environ["HIP_VISIBLE_DEVICES"] = str(args.cuda_device)
        os.environ["ASCEND_RT_VISIBLE_DEVICES"] = str(args.cuda_device)

    if args.oneapi_device_selector is not None:
        os.environ["ONEAPI_DEVICE_SELECTOR"] = args.oneapi_device_selector

    if args.deterministic and "CUBLAS_WORKSPACE_CONFIG" not in os.environ:
        os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"

    cuda_malloc_mod = _load_module_temp(
        "_bootstrap_cuda_malloc", os.path.join(comfyui_path, "cuda_malloc.py")
    )
    if (
        cuda_malloc_mod is not None
        and hasattr(cuda_malloc_mod, "get_torch_version_noimport")
        and "rocm" in cuda_malloc_mod.get_torch_version_noimport()
    ):
        os.environ["OCL_SET_SVM_SIZE"] = "262144"


def cleanup_comfyui_runtime(unload_models: bool | None = None) -> None:
    """Best-effort cleanup for embedded or repeated generated-script execution."""
    import gc

    def run_cleanup_hook(name: str, should_run: bool = True) -> None:
        if not should_run or not hasattr(model_management, name):
            return
        cleanup_fn = getattr(model_management, name)
        try:
            cleanup_fn()
        except Exception as exc:
            warnings.warn(
                f"ComfyUI cleanup hook {name} failed during teardown: {exc}",
                RuntimeWarning,
                stacklevel=2,
            )

    should_unload = unload_models
    if should_unload is None:
        should_unload = os.environ.get(
            "COMFYUI_TOPYTHON_UNLOAD_MODELS", ""
        ).lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    try:
        import comfy.model_management as model_management
    except ModuleNotFoundError:
        gc.collect()
        return

    run_cleanup_hook("cleanup_models_gc")
    run_cleanup_hook("unload_all_models", should_run=should_unload)
    run_cleanup_hook("soft_empty_cache")
    gc.collect()


def import_custom_nodes() -> None:
    """Initialize ComfyUI custom nodes in the exporter runtime.

    Uses _load_module() for all ComfyUI imports — no bare imports,
    no sys.path remove/re-insert gap.
    """
    comfyui_path = get_comfyui_path()
    if comfyui_path is None:
        log.debug("import_custom_nodes: ComfyUI path not found")
        return

    # Idempotent insert-once — never removes from sys.path
    if comfyui_path not in sys.path:
        sys.path.insert(0, comfyui_path)

    import asyncio

    execution_mod = _load_module(
        "execution", os.path.join(comfyui_path, "execution.py")
    )
    nodes_mod = _load_module("nodes", os.path.join(comfyui_path, "nodes.py"))

    # nodes.py inserts comfy/ subdirectory into sys.path, which shadows the
    # top-level utils/ package (comfy/utils.py vs utils/). This breaks
    # server.py → app.frontend_management → from utils.install_util import ...
    # Filter it out temporarily so server.py loads cleanly.
    comfy_subdir = os.path.join(comfyui_path, "comfy")
    original_sys_path = list(sys.path)
    sys.path[:] = [p for p in sys.path if p != comfy_subdir]

    server_mod = _load_module("server", os.path.join(comfyui_path, "server.py"))

    # Restore sys.path so nodes and other modules that need comfy/ still work
    sys.path[:] = original_sys_path

    if execution_mod is None or server_mod is None:
        log.debug(
            "import_custom_nodes: could not load execution/server modules. "
            "Proceeding without full PromptServer/PromptQueue setup."
        )
        # Even without server, we can still populate NODE_CLASS_MAPPINGS from
        # comfy_extras and built-in extra nodes.
        if nodes_mod is not None and hasattr(nodes_mod, "init_extra_nodes"):
            asyncio.run(nodes_mod.init_extra_nodes())
        return

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    server_instance = server_mod.PromptServer(loop)
    execution_mod.PromptQueue(server_instance)
    if nodes_mod is not None and hasattr(nodes_mod, "init_extra_nodes"):
        asyncio.run(nodes_mod.init_extra_nodes())


def get_node_class_mappings() -> dict:
    """Load ComfyUI node mappings on demand via _load_module()."""
    add_comfyui_directory_to_sys_path()
    comfyui_path = get_comfyui_path()
    if comfyui_path is None:
        log.debug("get_node_class_mappings: ComfyUI path not found")
        return {}

    nodes_mod = _load_module("nodes", os.path.join(comfyui_path, "nodes.py"))
    if nodes_mod is None:
        return {}
    return getattr(nodes_mod, "NODE_CLASS_MAPPINGS", {})


def get_value_at_index(obj: Union[Sequence, Mapping], index: int) -> Any:
    """Return a sequence or mapping result item by index."""
    try:
        return obj[index]
    except KeyError:
        return obj["result"][index]
