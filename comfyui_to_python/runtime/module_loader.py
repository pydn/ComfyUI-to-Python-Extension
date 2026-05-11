"""Module loading via importlib and controlled bootstrap imports.

This module provides two loading strategies:
  - _load_module(): Load from explicit file path using importlib.util
    (bypasses sys.path resolution, caches in sys.modules)
  - _bootstrap_import(): Load via standard __import__() for namespace packages
    (comfy.* resolves correctly through Python's package machinery)

All modules loaded here are considered trusted — the caller must ensure
the file paths and module names come from verified sources.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import sys
from typing import Any

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
