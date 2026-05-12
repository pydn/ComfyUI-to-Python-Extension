# Imports
import gc
import importlib.util
import json
import logging
import os
import random
import sys
import warnings
from typing import Sequence, Mapping, Any, Union

log = logging.getLogger(__name__)
# --- Embedded from runtime/module_loader.py ---

"""Module loading via importlib and controlled bootstrap imports.

This module provides two loading strategies:
  - _load_module(): Load from explicit file path using importlib.util
    (bypasses sys.path resolution, caches in sys.modules)
  - _bootstrap_import(): Load via standard __import__() for namespace packages
    (comfy.* resolves correctly through Python's package machinery)

All modules loaded here are considered trusted — the caller must ensure
the file paths and module names come from verified sources.
"""

log = logging.getLogger(__name__)


def _load_module(module_name: str, filepath: str) -> Any:
    """Load a Python module from an explicit file path, bypassing sys.path.

    Significantly reduces bare import shadowing risk by loading modules
    from verified file paths instead of relying on sys.path resolution.
    If exec_module() raises, the partially-loaded module is removed from
    sys.modules so subsequent calls start fresh.

    Args:
        module_name: Name to register in sys.modules (e.g., "nodes").
        filepath: Absolute path to the .py file to load.

    Returns:
        The loaded module object, or None if loading failed.
    """
    # Return cached module if already loaded — prevents re-execution
    # that would reset state (e.g. NODE_CLASS_MAPPINGS after init_extra_nodes).
    if module_name in sys.modules:
        return sys.modules[module_name]
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
        try:
            spec.loader.exec_module(mod)
        except BaseException:
            sys.modules.pop(module_name, None)
            raise
        return mod
    except BaseException as e:
        log.debug("Failed to load %s from %s: %s", module_name, filepath, e)
        sys.modules.pop(module_name, None)  # Also clean up on edge-case exceptions
        return None


def _load_module_temp(module_name: str, filepath: str) -> Any:
    """Load a module via _load_module() then remove it from sys.modules.

    Used during bootstrap for modules that ComfyUI's import chain also loads
    normally — prevents the cached copy from conflicting with later imports.

    Args:
        module_name: Temporary name for the module (removed after load).
        filepath: Absolute path to the .py file to load.

    Returns:
        The loaded module object, or None if loading failed.
    """
    mod = _load_module(module_name, filepath)
    sys.modules.pop(module_name, None)
    return mod


def _bootstrap_import(module_name: str) -> Any:
    """Import a ComfyUI module using normal import machinery.

    Uses __import__() so namespace packages (e.g. comfy/) resolve correctly.
    The module remains cached in sys.modules so later re-imports by ComfyUI's
    internal chain reuse the same instance (including parsed CLI args).

    An allowlist of permitted module name prefixes prevents arbitrary module
    loading. Only modules whose name starts with one of the allowed prefixes
    can be imported through this function.

    Args:
        module_name: Dotted Python module name (e.g., "comfy.cli_args").

    Returns:
        The loaded module object.

    Raises:
        ValueError: If the module name is not in the allowed prefix list.
        ModuleNotFoundError: If the module cannot be imported.
    """
    # Validate against allowlist — defense-in-depth against arbitrary imports
    _ALLOWED = ("comfy", "folder_paths", "execution", "nodes", "server")
    top_level = module_name.split(".")[0]
    if not any(
        top_level == prefix or module_name.startswith(prefix + ".")
        for prefix in _ALLOWED
    ):
        raise ValueError(
            f"Bootstrap import blocked: '{module_name}' is not in allowed prefixes "
            f"{list(_ALLOWED)}"
        )

    # Ensure parent namespace exists for dotted names (namespace package support)
    parts = module_name.split(".")
    for i in range(1, len(parts)):
        parent = ".".join(parts[:i])
        if parent not in sys.modules:
            __import__(parent)
    return __import__(module_name, fromlist=[""])


# --- Embedded from runtime/path_discovery.py ---

"""Path discovery for ComfyUI root and auxiliary files.

This module handles locating the ComfyUI checkout directory and related
files on disk. It provides multiple resolution strategies with structural
verification to ensure the target is a genuine ComfyUI installation.

Trust model: The caller must trust that the COMFYUI_PATH environment
variable or filesystem contents come from a verified source. This module
verifies structural markers (nodes.py, main.py, comfy/) but does NOT
verify content integrity of those files.
"""

log = logging.getLogger(__name__)


def _is_comfyui_directory(path: str) -> bool:
    """Verify a directory has ComfyUI structural markers.

    Checks for nodes.py, main.py, and the comfy/ subdirectory to raise
    the bar against spoofing via a directory with only a single marker file.

    Args:
        path: Directory path to verify.

    Returns:
        True if all three structural markers exist, False otherwise.
    """
    if not os.path.isdir(path):
        return False
    return (
        os.path.isfile(os.path.join(path, "nodes.py"))
        and os.path.isfile(os.path.join(path, "main.py"))
        and os.path.isdir(os.path.join(path, "comfy"))
    )


def _find_from_extension_location() -> str | None:
    """Walk up from this file's location to find ComfyUI root.

    Checks the starting directory first before walking upward. Uses
    realpath resolution to handle symlinks in custom node directories.

    Returns:
        Full path to ComfyUI root, or None if not found within 10 levels.
    """
    ext_dir = os.path.dirname(os.path.realpath(__file__))
    candidate = ext_dir
    for _ in range(10):
        if os.path.basename(candidate) == "ComfyUI":
            if _is_comfyui_directory(candidate):
                return candidate
        parent = os.path.dirname(candidate)
        if parent == candidate:
            break
        candidate = parent
    return None


def _find_file(name: str, max_depth: int = 20) -> str | None:
    """Walk up from CWD to find a file by name.

    Unlike find_path() which searches for directories, this checks
    os.path.isfile() at each level. Returns full path to the file or None.

    Checks CWD first before walking upward. Depth-limited to prevent slow
    startup on deep trees.

    Args:
        name: Basename of the file to find (e.g., "extra_model_paths.yaml").
        max_depth: Maximum directory levels to walk upward (default 20).

    Returns:
        Full path to the file, or None if not found.
    """
    candidate = os.getcwd()
    for _ in range(max_depth):
        filepath = os.path.join(candidate, name)
        if os.path.isfile(filepath):
            return filepath
        parent = os.path.dirname(candidate)
        if parent == candidate:
            break
        candidate = parent
    return None


def find_path(name: str, max_depth: int = 20) -> str | None:
    """Walk up from CWD to find a directory by name.

    Checks CWD first before walking upward. Depth-limited to prevent slow
    startup on deep trees. Each candidate should be verified by the caller
    (e.g., with _is_comfyui_directory()).

    Args:
        name: Basename of the directory to find (e.g., "ComfyUI").
        max_depth: Maximum directory levels to walk upward (default 20).

    Returns:
        Full path to the matching directory, or None if not found.
    """
    candidate = os.getcwd()
    for _ in range(max_depth):
        if os.path.basename(candidate) == name:
            return candidate
        parent = os.path.dirname(candidate)
        if parent == candidate:
            break
        candidate = parent
    return None


def get_comfyui_path() -> str | None:
    """Resolve ComfyUI path via prioritized multi-strategy fallback.

    Strategy order:
      1. COMFYUI_PATH env var (verified with _is_comfyui_directory)
      2. Relative walk from extension location (realpath + verified)
      3. CWD walk (legacy fallback, depth-limited)

    Returns:
        Full path to ComfyUI root directory, or None if not found.

    Note:
        The COMFYUI_PATH environment variable must be set by a trusted source.
        This module verifies structural markers but does not validate file
        contents. An attacker who controls the target directory could provide
        malicious nodes.py/main.py that pass structural checks.
    """
    p = os.environ.get("COMFYUI_PATH")
    if p and _is_comfyui_directory(p):
        return p
    p = _find_from_extension_location()
    if p:
        return p
    p = find_path("ComfyUI", max_depth=20)
    if p and _is_comfyui_directory(p):
        return p
    return None


# --- Embedded from runtime/bootstrap.py ---

"""CLI option discovery and argv filtering helpers.

This module provides internal utilities for:
  - Dynamic discovery of valid CLI options from ComfyUI's argparse parser
  - Filtering sys.argv to keep only ComfyUI-recognized flags

These are imported by node_runtime.py which contains the public
bootstrap_comfyui_runtime() function. Keeping them separate clarifies
the distinction between data analysis (this module) and runtime execution
(node_runtime.py).
"""

log = logging.getLogger(__name__)


# Module-level globals that must appear in generated standalone scripts.
_GENERATED_GLOBALS: list[str] = [
    "_DISCOVERED_OPTIONS = None",
]

# Cache for discovered CLI options — populated once, reused thereafter.
_DISCOVERED_OPTIONS: tuple[frozenset[str], frozenset[str]] | None = None


def _discover_comfyui_cli_options() -> tuple[frozenset[str], frozenset[str]]:
    """Dynamically discover CLI options from ComfyUI's argparse parser.

    Inspects `comfy.cli_args.parser._actions` to extract all recognized
    option strings and which ones take values. This eliminates the need for
    a hardcoded list that drifts when ComfyUI adds/removes flags.

    Results are cached after first call. Cache is process-lifetime — it is
    not automatically invalidated if ComfyUI code changes on disk.

    Returns:
        Tuple of (known_options, value_taking_options) as frozensets.
        value_taking_options is a subset of known_options.
    """
    global _DISCOVERED_OPTIONS  # noqa: PLW0603
    if _DISCOVERED_OPTIONS is not None:
        return _DISCOVERED_OPTIONS

    # Temporarily replace argv to parse with safe defaults during discovery.
    original_argv = sys.argv
    pre_discovery_modules = set(sys.modules.keys())
    # _bootstrap_import is provided by the embedding context:
    # imported at module level in package usage, or embedded as a standalone
    # function before this one in generated scripts (via inspect.getsource).
    try:
        sys.argv = ["_discover"]
        cli_args_mod = _bootstrap_import("comfy.cli_args")
    except ModuleNotFoundError:
        log.debug("comfy.cli_args not available for option discovery")
        sys.argv = original_argv
        _DISCOVERED_OPTIONS = frozenset(), frozenset()
        return _DISCOVERED_OPTIONS
    finally:
        sys.argv = original_argv

    # Remove ComfyUI modules loaded during discovery so that
    # bootstrap_comfyui_runtime() can import them fresh with real argv.
    for mod_name in set(sys.modules.keys()) - pre_discovery_modules:
        if mod_name.startswith("comfy.") or mod_name in (
            "cli_args",
            "folder_paths",
            "execution",
            "nodes",
            "server",
            "comfy_main",
        ):
            sys.modules.pop(mod_name, None)

    if cli_args_mod is None:
        log.debug("bootstrap returned None for comfy.cli_args")
        _DISCOVERED_OPTIONS = frozenset(), frozenset()
        return _DISCOVERED_OPTIONS

    parser = getattr(cli_args_mod, "parser", None)
    if parser is None:
        log.debug("Could not find parser in comfy.cli_args")
        _DISCOVERED_OPTIONS = frozenset(), frozenset()
        return _DISCOVERED_OPTIONS

    known: set[str] = set()
    value_taking: set[str] = set()
    for action in parser._actions:
        for opt in action.option_strings:
            if not opt.startswith("--"):
                continue
            # Strip inline default shown by argparse (e.g. '--listen [IP]')
            base = opt.split("[")[0].strip()
            known.add(base)
            nargs = getattr(action, "nargs", None)
            # Skip boolean store_true/store_false actions — they don't take values
            action_name = type(action).__name__
            if action_name in ("_StoreTrueAction", "_StoreFalseAction"):
                continue
            if nargs is not None and nargs != 0:
                value_taking.add(base)
            elif hasattr(action, "const") and action.const is not None:
                value_taking.add(base)
            elif getattr(action, "type", None) is not None or nargs is None:
                if action.dest != "help":
                    value_taking.add(base)

    _DISCOVERED_OPTIONS = frozenset(known), frozenset(value_taking)
    return _DISCOVERED_OPTIONS


def _filter_comfyui_args(argv: list[str]) -> list[str]:
    """Filter sys.argv to keep only ComfyUI-recognized CLI arguments.

    When bootstrap runs inside a subprocess (e.g. test runner), sys.argv may
    contain flags that aren't valid for ComfyUI's argparse. This filters them
    out so the import doesn't crash while still preserving --cpu and other
    ComfyUI flags passed by the user.

    Uses _discover_comfyui_cli_options() to dynamically discover recognized
    options from ComfyUI's parser rather than maintaining a hardcoded list.

    Handles edge cases:
      - Tokens like '--cuda-device=0' (inline =value)
      - Single-char flags are always skipped (-v, -s from test runners)
      - Unknown --flags and their values are dropped
      - Known option values that look like flags are preserved (not consumed as flags)

    Args:
        argv: List of command-line argument strings (typically sys.argv).

    Returns:
        Filtered list containing only recognized ComfyUI arguments.
    """
    known, value_taking = _discover_comfyui_cli_options()

    # Extract base option from tokens like '--cuda-device=0'
    def _base_option(token: str) -> str | None:
        if "=" in token:
            return token.split("=")[0]
        return token

    result = [argv[0]] if argv else []
    i = 1
    while i < len(argv):
        token = argv[i]
        # Skip single-char flags (e.g. -v, -s from test runners)
        if token.startswith("-") and not token.startswith("--"):
            i += 1
            continue
        base = _base_option(token)
        if base in known:
            result.append(token)
            # If the option takes a value and it's not inline (=), consume next arg
            if base in value_taking and "=" not in token:
                if i + 1 < len(argv):
                    next_token = argv[i + 1]
                    # Safety check: don't consume a known option as a value
                    if (
                        next_token.startswith("--")
                        and _base_option(next_token) in known
                    ):
                        pass  # Next token is itself a flag — don't consume it
                    elif not next_token.startswith("--"):
                        result.append(next_token)
                        i += 1
        elif token.startswith("--"):
            # Unknown --flag — skip it (and its value if present)
            if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                i += 1
        else:
            # Positional arg — keep it
            result.append(token)
        i += 1
    return result


# --- Embedded from node_runtime.py ---

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

# ── Re-exports from runtime/path_discovery.py ────────────────────────────────

# ── Re-exports from runtime/module_loader.py ────────────────────────────────

# ── Re-exports from runtime/bootstrap.py ────────────────────────────────────

log = logging.getLogger(__name__)


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
    if args.output_directory:
        folder_paths_mod = _bootstrap_import("folder_paths")
        if folder_paths_mod is not None and hasattr(
            folder_paths_mod, "set_output_directory"
        ):
            folder_paths_mod.set_output_directory(
                os.path.abspath(args.output_directory)
            )

    if args.input_directory:
        folder_paths_mod = _bootstrap_import("folder_paths")
        if folder_paths_mod is not None and hasattr(
            folder_paths_mod, "set_input_directory"
        ):
            folder_paths_mod.set_input_directory(os.path.abspath(args.input_directory))

    if args.user_directory:
        folder_paths_mod = _bootstrap_import("folder_paths")
        if folder_paths_mod is not None and hasattr(
            folder_paths_mod, "set_user_directory"
        ):
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
        # Guaranteed even if _load_module raises mid-execution.
        sys.path[:] = original_sys_path

    if execution_mod is None or server_mod is None:
        log.debug(
            "import_custom_nodes: could not load execution/server modules. "
            "Proceeding without full PromptServer/PromptQueue setup."
        )
        if nodes_mod is not None and hasattr(nodes_mod, "init_extra_nodes"):
            asyncio.run(nodes_mod.init_extra_nodes())
        return

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    server_instance = server_mod.PromptServer(loop)
    execution_mod.PromptQueue(server_instance)
    if nodes_mod is not None and hasattr(nodes_mod, "init_extra_nodes"):
        asyncio.run(nodes_mod.init_extra_nodes())


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


# Workflow data
def build_workflow() -> dict[str, Any]:
    return {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "v1-5-pruned-emaonly-fp16.safetensors"},
        },
        "2": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "text": "a small cottage in a meadow, soft daylight",
                "clip": ["1", 1],
            },
        },
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "blurry, low quality", "clip": ["1", 1]},
        },
        "4": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 512, "height": 512, "batch_size": 1},
        },
        "5": {
            "class_type": "KSampler",
            "inputs": {
                "seed": 1,
                "steps": 4,
                "cfg": 7,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": 1,
                "model": ["1", 0],
                "positive": ["2", 0],
                "negative": ["3", 0],
                "latent_image": ["4", 0],
            },
        },
        "6": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["5", 0], "vae": ["1", 2]},
        },
        "7": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": "E2E_text_to_image", "images": ["6", 0]},
        },
    }


def build_extra_pnginfo() -> dict[str, Any] | None:
    return None


workflow = build_workflow()
prompt = json.loads(json.dumps(workflow))
extra_pnginfo = build_extra_pnginfo()


# Workflow execution
def main(unload_models: bool | None = None):
    bootstrap_comfyui_runtime()
    add_extra_model_paths()

    # Node imports
    from nodes import (
        CLIPTextEncode,
        CheckpointLoaderSimple,
        EmptyLatentImage,
        KSampler,
        NODE_CLASS_MAPPINGS,
        SaveImage,
        VAEDecode,
    )

    import torch

    try:
        with torch.inference_mode():
            checkpointloadersimple = CheckpointLoaderSimple()
            checkpointloadersimple_1 = checkpointloadersimple.load_checkpoint(
                ckpt_name="v1-5-pruned-emaonly-fp16.safetensors"
            )
            cliptextencode = CLIPTextEncode()
            cliptextencode_2 = cliptextencode.encode(
                text="a small cottage in a meadow, soft daylight",
                clip=get_value_at_index(checkpointloadersimple_1, 1),
            )
            cliptextencode_3 = cliptextencode.encode(
                text="blurry, low quality",
                clip=get_value_at_index(checkpointloadersimple_1, 1),
            )
            emptylatentimage = EmptyLatentImage()
            emptylatentimage_4 = emptylatentimage.generate(
                width=512, height=512, batch_size=1
            )
            ksampler = KSampler()
            vaedecode = VAEDecode()
            saveimage = SaveImage()
            for q in range(1):
                node_5_seed = prompt["5"]["inputs"]["seed"] = random.randint(1, 2**64)
                ksampler_5 = ksampler.sample(
                    seed=node_5_seed,
                    steps=4,
                    cfg=7,
                    sampler_name="euler",
                    scheduler="normal",
                    denoise=1,
                    model=get_value_at_index(checkpointloadersimple_1, 0),
                    positive=get_value_at_index(cliptextencode_2, 0),
                    negative=get_value_at_index(cliptextencode_3, 0),
                    latent_image=get_value_at_index(emptylatentimage_4, 0),
                )
                vaedecode_6 = vaedecode.decode(
                    samples=get_value_at_index(ksampler_5, 0),
                    vae=get_value_at_index(checkpointloadersimple_1, 2),
                )
                saveimage_7 = saveimage.save_images(
                    filename_prefix="E2E_text_to_image",
                    images=get_value_at_index(vaedecode_6, 0),
                    prompt=prompt,
                    extra_pnginfo=extra_pnginfo,
                )
    finally:
        cleanup_comfyui_runtime(unload_models=unload_models)


# Entrypoint
if __name__ == "__main__":
    main()
