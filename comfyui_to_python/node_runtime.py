import importlib.util
import logging
import os
import sys
import warnings
from typing import Any, Mapping, Sequence, Union

log = logging.getLogger(__name__)


def _is_comfyui_directory(path: str) -> bool:
    """Verify a directory has ComfyUI structural markers.

    Checks for nodes.py, main.py, and the comfy/ subdirectory to raise
    the bar against spoofing via a directory with only a single marker file.
    """
    if not os.path.isdir(path):
        return False
    return (
        os.path.isfile(os.path.join(path, "nodes.py"))
        and os.path.isfile(os.path.join(path, "main.py"))
        and os.path.isdir(os.path.join(path, "comfy"))
    )


def _load_module(module_name: str, filepath: str) -> Any:
    """Load a Python module from an explicit file path, bypassing sys.path.

    Significantly reduces bare import shadowing risk by loading modules
    from verified file paths instead of relying on sys.path resolution.
    If exec_module() raises, the partially-loaded module is removed from
    sys.modules so subsequent calls start fresh.
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


def _find_from_extension_location() -> str | None:
    """Walk up from this file's location to find ComfyUI root.

    Checks the starting directory first before walking upward.
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

    Checks CWD first before walking upward.
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
    """Iteratively walk up from CWD to find a directory by name.

    Checks CWD first before walking upward. Depth-limited to prevent slow
    startup on deep trees. Each candidate verified by _is_comfyui_directory()
    at the caller.
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

    extra_model_paths = _find_file("extra_model_paths.yaml")
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


def _bootstrap_import(module_name: str) -> Any:
    """Import a ComfyUI module using normal import machinery.

    Uses __import__() so namespace packages (e.g. comfy/) resolve correctly.
    The module remains cached in sys.modules so later re-imports by ComfyUI's
    internal chain reuse the same instance (including parsed CLI args).
    """
    # Ensure parent namespace exists for dotted names (namespace package support)
    parts = module_name.split(".")
    for i in range(1, len(parts)):
        parent = ".".join(parts[:i])
        if parent not in sys.modules:
            __import__(parent)
    return __import__(module_name, fromlist=[""])


_DISCOVERED_OPTIONS: tuple[frozenset[str], frozenset[str]] | None = None


def _discover_comfyui_cli_options() -> tuple[frozenset[str], frozenset[str]]:
    """Dynamically discover CLI options from ComfyUI's argparse parser.

    Inspects `comfy.cli_args.parser._actions` to extract all recognized
    option strings and which ones take values. This eliminates the need for
    a hardcoded list that drifts when ComfyUI adds/removes flags.

    Returns:
        (known_options, value_taking_options) — frozensets of option strings.
        value_taking_options is a subset of known_options.
    """
    global _DISCOVERED_OPTIONS
    if _DISCOVERED_OPTIONS is not None:
        return _DISCOVERED_OPTIONS

    # Temporarily replace argv to parse with safe defaults during discovery.
    original_argv = sys.argv
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
            # Determine if the option takes a value argument.
            # nargs=None means a required value; numeric nargs means N values;
            # nargs='?' means optional value (still count as value-taking for
            # filtering since --flag value is valid).
            nargs = getattr(action, "nargs", None)
            # Skip boolean store_true/store_false actions — they don't take values
            action_name = type(action).__name__
            if action_name in ("_StoreTrueAction", "_StoreFalseAction"):
                continue
            if nargs is not None and nargs != 0:
                value_taking.add(base)
            elif hasattr(action, "const") and action.const is not None:
                # Optional value with const default (e.g. --listen without arg)
                value_taking.add(base)
            elif getattr(action, "type", None) is not None or nargs is None:
                # Has a type converter → requires a value.
                # nargs defaults to None for single-value args.
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
                if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                    result.append(argv[i + 1])
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


def bootstrap_comfyui_runtime() -> None:
    """Mirror the allocator-related ComfyUI startup steps before torch import.

    Uses normal imports so that parsed CLI args (e.g. --cpu) persist in
    sys.modules and are reused when ComfyUI's internal chain later imports
    comfy.cli_args and comfy.options.
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
    # Modules are cached in sys.modules under canonical names so parsed CLI
    # args persist for the full runtime lifecycle.
    options_mod = _bootstrap_import("comfy.options")
    if options_mod is not None:
        options_mod.enable_args_parsing()

    cli_args_mod = _bootstrap_import("comfy.cli_args")

    # Restore original argv so that downstream code sees what was actually passed
    sys.argv = original_argv
    args = getattr(cli_args_mod, "args", None) if cli_args_mod else None

    # If the user didn't pass --cpu but CUDA is unavailable (no GPU/driver),
    # force CPU mode so model_management doesn't crash on CUDA init.
    if args is not None and not args.cpu:
        try:
            import torch as _torch

            if not _torch.cuda.is_available():
                args.cpu = True
        except Exception:
            pass  # If we can't check, let ComfyUI handle the error

    # Modules stay in sys.modules so parsed CLI args (e.g. --cpu) persist when
    # ComfyUI's internal chain reuses the cached cli_args module.

    if os.name == "nt":
        os.environ["MIMALLOC_PURGE_DELAY"] = "0"

    # Guard all args access — args may be None during export path
    if args is not None:
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
    """Load ComfyUI node mappings on demand via _load_module().

    Calls bootstrap_comfyui_runtime() first so that CLI args (e.g. --cpu)
    are parsed and cached in sys.modules before nodes.py triggers the
    comfy.cli_args import chain. This prevents CUDA init crashes on
    systems without a GPU.

    Reuses the cached "nodes" module from sys.modules if already loaded
    (e.g. by import_custom_nodes) to avoid resetting NODE_CLASS_MAPPINGS.
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


def get_value_at_index(obj: Union[Sequence, Mapping], index: int) -> Any:
    """Return a sequence or mapping result item by index."""
    try:
        return obj[index]
    except KeyError:
        return obj["result"][index]
