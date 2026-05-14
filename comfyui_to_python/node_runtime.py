"""Node runtime: ComfyUI import path resolution, module loading, and bootstrap.

This module is the public facade for the <code>comfyui_to_python.runtime</code>
subpackage. All imports that previously came from this file continue to work
unchanged — the internal implementation has been reorganized into focused
submodules for clarity.

Submodule structure:
  runtime/path_discovery.py  — Locate ComfyUI root and auxiliary files
  runtime/module_loader.py   — Load Python modules via importlib/bootstrap
  runtime/bootstrap.py       — CLI discovery, argv filtering, runtime init

Public API (import from this module):
  Path resolution: get_comfyui_path(), find_path(), add_comfyui_directory_to_sys_path()
  Model paths:     add_extra_model_paths()
  Bootstrap:       bootstrap_comfyui_runtime()
  Cleanup:         cleanup_comfyui_runtime()
  Custom nodes:    import_custom_nodes()
  Node mappings:   get_node_class_mappings()
  Helpers:         get_value_at_index()

Internal (prefixed with _): Available for embedding in generated scripts.
"""

from __future__ import annotations

import gc
import logging
import os
import sys
import warnings
from typing import Any, Mapping, Sequence, Union

# ── Re-exports from runtime/bootstrap.py ────────────────────────────────────
from .runtime.bootstrap import (
    _DISCOVERED_OPTIONS,
    _discover_comfyui_cli_options,
    _filter_comfyui_args,
)

# ── Re-exports from runtime/module_loader.py ────────────────────────────────
from .runtime.module_loader import (
    _bootstrap_import,
    _load_module,
    _load_module_temp,
)

# ── Re-exports from runtime/path_discovery.py ────────────────────────────────
from .runtime.path_discovery import (
    _find_file,
    _find_from_extension_location,
    _is_comfyui_directory,
    find_path,
    get_comfyui_path,
)

log = logging.getLogger(__name__)


# ── Public API ────────────────────────────────────────────────────────────────
# Re-exported names for import from this module.
# External code imports these from comfyui_to_python.node_runtime (not submodules).
__all__: list[str] = [
    # Path discovery
    "_find_file",
    "_find_from_extension_location",
    "_is_comfyui_directory",
    "add_comfyui_directory_to_sys_path",
    "find_path",
    "get_comfyui_path",
    # Module loading
    "_bootstrap_import",
    "_load_module",
    "_load_module_temp",
    # Bootstrap / CLI
    "_DISCOVERED_OPTIONS",
    "_discover_comfyui_cli_options",
    "_filter_comfyui_args",
    # Public API
    "add_extra_model_paths",
    "bootstrap_comfyui_runtime",
    "cleanup_comfyui_runtime",
    "get_node_class_mappings",
    "get_value_at_index",
    "import_custom_nodes",
]


# ── Public API: sys.path management ─────────────────────────────────────────


def add_comfyui_directory_to_sys_path() -> None:
    """Add the ComfyUI checkout to sys.path (idempotent — always at index 0).

    If already present but lower in sys.path, removes and re-inserts at front
    so bare imports always resolve to this copy first.
    """
    comfyui_path = get_comfyui_path()
    if comfyui_path is not None and os.path.isdir(comfyui_path):
        if comfyui_path in sys.path:
            sys.path.remove(comfyui_path)
        sys.path.insert(0, comfyui_path)
        log.debug("Added %s to sys.path[0]", comfyui_path)


def add_extra_model_paths() -> None:
    """Load ComfyUI extra model paths configuration when available.

    Attempts to load <code>load_extra_path_config</code> from ComfyUI's main.py,
    falling back to utils/extra_config.py if main.py is unavailable.
    Then locates and loads the extra_model_paths.yaml configuration file.
    """
    comfyui_path = get_comfyui_path()
    if comfyui_path is None:
        log.debug("Cannot load extra model paths: ComfyUI path not found")
        return

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

    extra_model_paths = _find_file("extra_model_paths.yaml")
    if extra_model_paths is not None:
        load_extra_path_config(extra_model_paths)
    else:
        log.debug("Could not find the extra_model_paths config file.")


# ── Public API: bootstrap (self-contained for generated script embedding) ────


def bootstrap_comfyui_runtime() -> None:
    """Mirror the allocator-related ComfyUI startup steps before torch import.

    Uses normal imports so that parsed CLI args (e.g. --cpu) persist in
    sys.modules and are reused when ComfyUI's internal chain later imports
    comfy.cli_args and comfy.options.

    Sequence:
      1. Add ComfyUI to sys.path[0]
      2. Filter sys.argv to known ComfyUI options
      3. Import and enable CLI arg parsing via _bootstrap_import()
      4. Force --cpu mode if CUDA is unavailable
      5. Apply device, directory, and allocator settings from parsed args
      6. Load cuda_malloc.py for ROCm detection (temp module)
    """
    add_comfyui_directory_to_sys_path()
    comfyui_path = get_comfyui_path()
    if comfyui_path is None:
        log.debug("bootstrap_comfyui_runtime: ComfyUI path not found")
        return

    # Filter sys.argv to keep only ComfyUI-recognized flags. This prevents
    # argparse crashes when bootstrap runs inside a subprocess (e.g. test
    # runner) where sys.argv contains non-ComfyUI arguments.
    original_argv = sys.argv
    sys.argv = _filter_comfyui_args(sys.argv)

    # Load via _bootstrap_import() for namespace-package-safe imports.
    options_mod = _bootstrap_import("comfy.options")
    if options_mod is not None:
        options_mod.enable_args_parsing()

    cli_args_mod = _bootstrap_import("comfy.cli_args")

    # Restore original argv so that downstream code sees what was actually passed
    sys.argv = original_argv
    args = getattr(cli_args_mod, "args", None) if cli_args_mod else None

    if os.name == "nt":
        os.environ["MIMALLOC_PURGE_DELAY"] = "0"

    # Guard all args access — args may be None during export path
    if args is not None:
        _apply_device_settings(args)
        _apply_directory_overrides(args)

    cuda_malloc_mod = _load_module_temp(
        "_bootstrap_cuda_malloc", os.path.join(comfyui_path, "cuda_malloc.py")
    )
    if (
        cuda_malloc_mod is not None
        and hasattr(cuda_malloc_mod, "get_torch_version_noimport")
        and "rocm" in cuda_malloc_mod.get_torch_version_noimport()
    ):
        os.environ["OCL_SET_SVM_SIZE"] = "262144"


def _apply_device_settings(args: Any) -> None:
    """Apply GPU device settings from parsed CLI arguments.

    Sets environment variables for CUDA, HIP, and oneAPI device selection
    based on the user's command-line arguments.
    """
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


def _apply_directory_overrides(args: Any) -> None:
    """Apply output/input/user directory overrides from CLI arguments.

    Redirects ComfyUI's default directories to user-specified paths,
    enabling operation when default mounts are read-only.
    """
    folder_paths_mod = _bootstrap_import("folder_paths")
    if folder_paths_mod is None:
        return

    if args.output_directory and hasattr(folder_paths_mod, "set_output_directory"):
        folder_paths_mod.set_output_directory(os.path.abspath(args.output_directory))
    if args.input_directory and hasattr(folder_paths_mod, "set_input_directory"):
        folder_paths_mod.set_input_directory(os.path.abspath(args.input_directory))
    if args.user_directory and hasattr(folder_paths_mod, "set_user_directory"):
        folder_paths_mod.set_user_directory(os.path.abspath(args.user_directory))


# ── Public API: cleanup ─────────────────────────────────────────────────────


def cleanup_comfyui_runtime(unload_models: bool | None = None) -> None:
    """Best-effort cleanup for embedded or repeated generated-script execution.

    Runs ComfyUI's model cleanup hooks and garbage collection. Designed for
    scenarios where the script is executed repeatedly within a single process
    (e.g., notebook cells, test runners).

    Args:
        unload_models: Force model unloading. If None, reads from
            COMFYUI_TOPYTHON_UNLOAD_MODELS environment variable.
    """

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
        ).lower() in {"1", "true", "yes", "on"}

    try:
        import comfy.model_management as model_management  # noqa: PLC0414
    except ModuleNotFoundError:
        gc.collect()
        return

    run_cleanup_hook("cleanup_models_gc")
    run_cleanup_hook("unload_all_models", should_run=should_unload)
    run_cleanup_hook("soft_empty_cache")
    gc.collect()


# ── Public API: custom nodes ────────────────────────────────────────────────


def _load_custom_node_modules(
    comfyui_path: str,
) -> tuple[Any, Any, Any]:
    """Load the three core ComfyUI modules for custom node initialization.

    Loads execution.py, nodes.py, and server.py from the ComfyUI checkout.
    Temporarily filters out comfy/ subdirectory from sys.path to prevent
    import shadowing when loading server.py.

    Args:
        comfyui_path: Absolute path to the ComfyUI root directory.

    Returns:
        Tuple of (execution_mod, nodes_mod, server_mod). Any may be None
        if the corresponding module could not be loaded.
    """
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

    try:
        server_mod = _load_module("server", os.path.join(comfyui_path, "server.py"))
    finally:
        # Restore sys.path so nodes and other modules that need comfy/ still work.
        sys.path[:] = original_sys_path

    return execution_mod, nodes_mod, server_mod


def _init_extra_nodes(nodes_mod: Any) -> None:
    """Call init_extra_nodes on the nodes module if available.

    Args:
        nodes_mod: The loaded nodes module (may be None).
    """
    import asyncio

    if nodes_mod is not None and hasattr(nodes_mod, "init_extra_nodes"):
        asyncio.run(nodes_mod.init_extra_nodes())


def import_custom_nodes() -> None:
    """Initialize ComfyUI custom nodes in the exporter runtime.

    Loads execution.py, nodes.py, and server.py from the ComfyUI checkout.
    Sets up PromptServer and PromptQueue for the async event loop.
    Calls init_extra_nodes() to populate NODE_CLASS_MAPPINGS with extras.

    Uses _load_module() for all ComfyUI imports — no bare imports,
    no sys.path remove/re-insert gap.
    """
    import asyncio

    comfyui_path = get_comfyui_path()
    if comfyui_path is None:
        log.debug("import_custom_nodes: ComfyUI path not found")
        return

    # Idempotent insert-once — never removes from sys.path
    if comfyui_path not in sys.path:
        sys.path.insert(0, comfyui_path)

    execution_mod, nodes_mod, server_mod = _load_custom_node_modules(comfyui_path)

    if execution_mod is None or server_mod is None:
        log.debug(
            "import_custom_nodes: could not load execution/server modules. "
            "Proceeding without full PromptServer/PromptQueue setup."
        )
        _init_extra_nodes(nodes_mod)
        return

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    server_instance = server_mod.PromptServer(loop)
    execution_mod.PromptQueue(server_instance)
    _init_extra_nodes(nodes_mod)


# ── Public API: node mappings ───────────────────────────────────────────────


def get_node_class_mappings() -> dict:
    """Load ComfyUI node mappings on demand via _load_module().

    Calls bootstrap_comfyui_runtime() first so that CLI args (e.g. --cpu)
    are parsed and cached in sys.modules before nodes.py triggers the
    comfy.cli_args import chain. This prevents CUDA init crashes on
    systems without a GPU.

    Reuses the cached "nodes" module from sys.modules if already loaded
    (e.g. by import_custom_nodes) to avoid resetting NODE_CLASS_MAPPINGS.

    Returns:
        Dictionary mapping node class names to class objects, or empty dict
        if nodes module could not be loaded.
    """
    add_comfyui_directory_to_sys_path()
    comfyui_path = get_comfyui_path()
    if comfyui_path is None:
        log.debug("get_node_class_mappings: ComfyUI path not found")
        return {}

    # Ensure bootstrap has run so that parsed CLI args are cached in
    # sys.modules before nodes.py triggers the comfy import chain.
    bootstrap_comfyui_runtime()

    # Reuse cached module if already loaded to avoid resetting mappings.
    nodes_mod = sys.modules.get("nodes")
    if nodes_mod is None:
        nodes_mod = _load_module("nodes", os.path.join(comfyui_path, "nodes.py"))
    if nodes_mod is None:
        return {}
    return getattr(nodes_mod, "NODE_CLASS_MAPPINGS", {})


# ── Public API: helpers ─────────────────────────────────────────────────────


def get_value_at_index(obj: Union[Sequence, Mapping], index: int) -> Any:
    """Return a sequence or mapping result item by index.

    Used in generated scripts to extract items from ComfyUI node outputs.
    Supports both list indexing and dict key access with "result" fallback.

    Args:
        obj: A sequence (list, tuple) or mapping (dict) to index into.
        index: Integer index for sequences, or dict key / numeric fallback.

    Returns:
        The item at the given index, or the result[index] value for dicts.
    """
    try:
        return obj[index]
    except KeyError:
        return obj["result"][index]
