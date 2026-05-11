# Harden import path resolution for all environments

## Problem

Generated scripts fail with `ModuleNotFoundError` and import shadowing issues across diverse ComfyUI installations — especially on Windows, in custom node directories outside `custom_nodes/`, or when multiple Python packages share names with ComfyUI internals (e.g., a `utils/` directory). The existing code relied on bare imports (`import execution`, `from nodes import ...`) and fragile `sys.path` manipulation that assumes ComfyUI is at a predictable location.

## What Changed

**17 commits, +3044 / -236 lines across 19 files.** Three major improvement areas:

### 1. Full `importlib` Isolation (Approach B)

- **`_load_module()`**: Centralized function that loads Python modules from explicit file paths via `importlib.util.spec_from_file_location()`, bypassing `sys.path` resolution entirely. If `exec_module()` raises, the partially-loaded module is removed from `sys.modules` so subsequent calls start fresh.
- **`_load_module_temp()`**: Variant that removes the module from `sys.modules` after loading — used during bootstrap for modules ComfyUI's import chain also loads normally.
- All ComfyUI internal imports (`execution.py`, `nodes.py`, `server.py`, `main.py`, etc.) now use `_load_module()` instead of bare `import`.

**Security benefit**: Eliminates module shadowing attacks. Even if a malicious package is at `sys.path[0]`, `_load_module()` loads from the verified ComfyUI checkout path, not from `sys.path` resolution.

### 2. CLI Arguments Propagation Fix

- **`_bootstrap_import()`**: Imports namespace packages (`comfy.options`, `comfy.cli_args`) using normal Python import machinery so they remain cached in `sys.modules`. When ComfyUI's internal chain later imports the same modules, it gets the cached instance with already-parsed CLI args (e.g., `--cpu`).
- **`_filter_comfyui_args()`**: Dynamically discovers valid CLI options from ComfyUI's argparse parser by inspecting `comfy.cli_args.parser._actions`. No hardcoded flag list — automatically stays in sync when ComfyUI adds/removes flags.
- **`_discover_comfyui_cli_options()`**: Caches discovered options as frozensets. Filters out non-ComfyUI arguments (e.g., test runner flags like `-v`, `-s`) before passing to argparse.

**Result**: `--cpu`, `--highvram`, `--reserve-vram`, and all other ComfyUI CLI flags now propagate correctly through generated scripts. Verified with E2E runtime tests against real ComfyUI on CPU-only hardware (14 boolean flags, 6 value-taking args, 3 enums — 41/41 passed).

### 3. Readability Refactor

Split the monolithic `node_runtime.py` (~75 lines) into focused submodules:

| Module | Responsibility |
|--------|---------------|
| `runtime/path_discovery.py` | Multi-strategy ComfyUI path resolution with structural verification |
| `runtime/module_loader.py` | `_load_module()`, `_bootstrap_import()` isolation layer |
| `runtime/bootstrap.py` | Dynamic CLI arg discovery and filtering |

The facade module (`node_runtime.py`) re-exports all public APIs — existing imports continue to work unchanged.

### 4. Path Resolution Hardening

- **`_is_comfyui_directory()`**: Verifies directories have ComfyUI structural markers (`nodes.py`, `main.py`, `comfy/`). Rejects spoofed or empty paths.
- **`get_comfyui_path()`**: Three-strategy fallback: (1) `COMFYUI_PATH` env var, (2) relative walk from extension location with realpath resolution, (3) CWD upward walk. All strategies verify structural markers.
- **`add_comfyui_directory_to_sys_path()`**: Idempotent insert at `sys.path[0]`. If already present but lower in sys.path, promotes to front — no remove/re-insert gap window.

### 5. Generated Script Updates

- All embedded helpers now include the isolation layer functions (`_load_module`, `_bootstrap_import`, etc.)
- Added required stdlib imports: `import importlib.util`, `import logging`, `import warnings`
- Zero bare imports of ComfyUI internals in generated output (verified by test)

## Testing

- **98 tests pass, 0 errors, 6 skipped** (up from 84 tests — previously `test_runtime_validation_harness` was excluded due to missing `__init__.py`)
- New test files:
  - `test_import_path_resolution.py` (735 lines) — isolation layer, shadowing resistance, path resolution strategies, sys.path idempotence, generated script output
  - `test_cli_args_propagation.py` (442 lines) — CLI arg caching, `_filter_comfyui_args()` edge cases, dynamic discovery
  - `test_app_base_mappings.py` (165 lines) — base_node_class_mappings stability across custom node reloads
- E2E runtime validation: All tested ComfyUI CLI args propagate correctly on CPU-only hardware with real `/opt/ComfyUI` checkout

## Backward Compatibility

**No breaking changes.** The facade module re-exports all existing public APIs. Generated scripts remain valid Python 3.12+ and use the same function signatures.

### Upstream Issues Addressed

| Issue | Description | How This PR Addresses It |
|-------|-------------|--------------------------|
| [#105](https://github.com/pydn/ComfyUI-to-Python-Extension/issues/105) | `ModuleNotFoundError: 'utils.json_util'` — not a package | `_load_module()` loads from verified paths, avoiding shadowing conflicts |
| [#117](https://github.com/pydn/ComfyUI-to-Python-Extension/issues/117) | Same utils import failure | Same fix as #105 |
| [#44](https://github.com/pydn/ComfyUI-to-Python-Extension/issues/44) | Set VRAM mode programmatically | CLI args now propagate through generated scripts (`--highvram`, `--lowvram`, etc.) |
| [#19](https://github.com/pydn/ComfyUI-to-Python-Extension/issues/19) | FileNotFoundError / import failures on Windows | Structural path verification + explicit file paths reduce platform-dependent resolution failures |

## Checklist

- [x] All tests passing (98 tests, 0 errors, 6 skipped)
- [x] Ralph review cycle completed — Cycle 2: **LGTM** (zero critical issues)
- [x] Generated scripts verified against real ComfyUI runtime
- [x] Backward compatibility maintained — no breaking API changes
- [x] pyproject.toml updated with proper package discovery and dev dependencies
