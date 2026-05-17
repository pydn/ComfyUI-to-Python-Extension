"""Auto-discover and embed all runtime helpers as a single block.

Instead of manually curating a __all__ list per function (which breaks when
new internal helpers are added), this module reads contributing source files,
strips their import statements via AST, and returns the clean definitions
ready for embedding in generated standalone scripts.

This guarantees that ALL functions, classes, and constants from the
contributing modules are embedded together — so internal cross-calls always
resolve without NameError.
"""

from __future__ import annotations

import ast
from pathlib import Path

# Modules whose top-level definitions should be embedded in generated scripts.
# Order matters: dependencies first, so functions are defined before callers use them.
_SOURCE_FILES: list[str] = [
    "runtime/module_loader.py",  # _load_module, _bootstrap_import — no internal deps
    "runtime/path_discovery.py",  # get_comfyui_path, find_path, etc.
    "runtime/bootstrap.py",  # CLI filtering; depends on module_loader
    "node_runtime.py",  # public API facade + bootstrap/cleanup
]


APPROVED_EMBEDDED_NAMES: frozenset[str] = frozenset(
    {
        "_apply_device_settings",
        "_apply_directory_overrides",
        "_bootstrap_import",
        "_discover_comfyui_cli_options",
        "_filter_comfyui_args",
        "_find_file",
        "_find_from_extension_location",
        "_get_base_option",
        "_init_extra_nodes",
        "_is_comfyui_directory",
        "_load_custom_node_modules",
        "_load_module",
        "_load_module_temp",
        "_parse_parser_actions",
        "add_comfyui_directory_to_sys_path",
        "add_extra_model_paths",
        "bootstrap_comfyui_runtime",
        "cleanup_comfyui_runtime",
        "find_path",
        "get_comfyui_path",
        "get_node_class_mappings",
        "get_value_at_index",
        "import_custom_nodes",
    }
)


def _strip_imports(source: str) -> str:
    """Remove all top-level import statements from Python source code.

    Uses AST to find import nodes and rebuilds the source with those lines
    removed while preserving everything else (functions, classes, constants,
    docstrings, comments).

    Args:
        source: Full Python source code of a module.

    Returns:
        Source code with all top-level import statements removed.
    """
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)

    # Collect line numbers (1-indexed) of top-level imports to remove
    skip_lines: set[int] = set()
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            # Handle multi-line imports (from x import (a,\n    b))
            start = node.lineno or 1
            end = getattr(node, "end_lineno", start) or start
            for ln in range(start, end + 1):
                skip_lines.add(ln)

    # Also strip blank lines that immediately follow removed imports
    # to avoid excessive whitespace gaps
    result_lines: list[str] = []
    prev_was_import = False
    for i, line in enumerate(lines, start=1):
        if i in skip_lines:
            prev_was_import = True
            continue
        # Skip a single blank line after imports (but keep meaningful spacing)
        if prev_was_import and line.strip() == "":
            prev_was_import = False
            continue
        prev_was_import = False
        result_lines.append(line)

    return "".join(result_lines).strip() + "\n"


def get_embedded_helpers() -> str:
    """Return the full embedded helper block for generated scripts.

    Reads each source file listed in _SOURCE_FILES, strips its import
    statements, and concatenates the results into a single embeddable
    code block.

    Returns:
        Python source code containing all function/class/constant definitions
        from contributing modules, ready to paste into a generated script.
    """
    package_root = Path(__file__).resolve().parent.parent  # comfyui_to_python/
    parts: list[str] = []

    for rel_path in _SOURCE_FILES:
        filepath = package_root / rel_path
        if not filepath.exists():
            raise FileNotFoundError(
                f"Embedded source file not found: {filepath}\n"
                f"If you added a new contributing module, update "
                f"_SOURCE_FILES in {__file__}"
            )
        parts.append(f"# --- Embedded from {rel_path} ---\n")
        parts.append(_strip_imports(filepath.read_text()))

    return "\n".join(parts)


def verify_embedded_surface_matches_manifest() -> list[str]:
    """Return embedded helper names that differ from the approved surface."""
    actual = list_embedded_names()
    differences = [
        *(
            f"missing approved embedded name: {name}"
            for name in sorted(APPROVED_EMBEDDED_NAMES - actual)
        ),
        *(
            f"unexpected embedded name: {name}"
            for name in sorted(actual - APPROVED_EMBEDDED_NAMES)
        ),
    ]
    return differences


def list_embedded_names() -> set[str]:
    """Return the set of all top-level names that will be embedded.

    Useful for testing / verification to ensure no unexpected names are
    included and to check for missing dependencies.

    Returns:
        Set of function/class/constant names from contributing modules.
    """
    package_root = Path(__file__).resolve().parent.parent
    names: set[str] = set()

    for rel_path in _SOURCE_FILES:
        filepath = package_root / rel_path
        tree = ast.parse(filepath.read_text())
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        # Skip common non-embeddable names like 'log'
                        if target.id not in ("log",):
                            names.add(target.id)

    return names


def verify_no_missing_cross_calls() -> list[str]:
    """Check that all function calls within embedded code resolve to embedded names.

    Scans each contributing module for calls to names defined at module level
    in other modules, and reports any that are NOT in the embedded set.

    Skips builtins, exceptions, type hints, and local/nested function references
    that are created dynamically (e.g., via getattr on runtime-loaded modules).

    Returns:
        List of unresolved call names (empty if everything resolves).
    """
    import builtins as _builtins

    embedded = list_embedded_names()
    package_root = Path(__file__).resolve().parent.parent
    builtin_names = set(dir(_builtins))

    # Exception classes that are common in error handling
    exception_names = {
        "Exception",
        "BaseException",
        "ValueError",
        "TypeError",
        "KeyError",
        "AttributeError",
        "ModuleNotFoundError",
        "ImportError",
        "FileNotFoundError",
        "RuntimeError",
        "StopIteration",
        "IndexError",
        "OSError",
    }

    # Type hint names from typing module
    typing_names = {
        "Any",
        "Sequence",
        "Mapping",
        "Union",
        "Optional",
        "List",
        "Dict",
        "Set",
        "Tuple",
        "FrozenSet",
        "Callable",
    }

    all_known = builtin_names | exception_names | typing_names | embedded
    unresolved: list[str] = []

    for rel_path in _SOURCE_FILES:
        filepath = package_root / rel_path
        tree = ast.parse(filepath.read_text())

        # Find all Name nodes used as function calls
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                caller_name = node.func.id
                if caller_name not in all_known:
                    # Could be a local/nested function or dynamic lookup — check if
                    # it's defined as a nested def anywhere in the same file
                    is_nested = _is_nested_or_local_def(filepath, caller_name)
                    if not is_nested:
                        unresolved.append(
                            f"{rel_path}: calls '{caller_name}' "
                            "(not embedded, not builtin)"
                        )

    return unresolved


def _is_nested_or_local_def(filepath: Path, name: str) -> bool:
    """Check if a name is defined as a nested function or local variable in a file.

    Catches patterns like:
      def outer():
          if cond:
              x = getattr(mod, "x")  # 'x' is a local var (nested inside if)
          return x()
    """
    tree = ast.parse(filepath.read_text())
    nested_defs: set[str] = set()
    local_assigns: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Walk ALL descendants of the function body to find nested defs
            # and local variable assignments (including those inside if/else blocks)
            for child in ast.walk(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    nested_defs.add(child.name)
                elif isinstance(child, ast.Assign):
                    for target in child.targets:
                        if isinstance(target, ast.Name):
                            local_assigns.add(target.id)

    return name in nested_defs or name in local_assigns
