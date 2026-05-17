"""Path discovery for ComfyUI root and auxiliary files.

This module handles locating the ComfyUI checkout directory and related
files on disk. It provides multiple resolution strategies with structural
verification to ensure the target is a genuine ComfyUI installation.

Trust model: The caller must trust that the COMFYUI_PATH environment
variable or filesystem contents come from a verified source. This module
verifies structural markers (nodes.py, main.py, comfy/) but does NOT
verify content integrity of those files.
"""

from __future__ import annotations

import logging
import os

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
