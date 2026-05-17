"""CLI option discovery and argv filtering helpers.

This module provides internal utilities for:
  - Dynamic discovery of valid CLI options from ComfyUI's argparse parser
  - Filtering sys.argv to keep only ComfyUI-recognized flags

These are imported by node_runtime.py which contains the public
bootstrap_comfyui_runtime() function. Keeping them separate clarifies
the distinction between data analysis (this module) and runtime execution
(node_runtime.py).
"""

from __future__ import annotations

import logging
import sys

from .module_loader import _bootstrap_import

log = logging.getLogger(__name__)


# Cache for discovered CLI options — populated once, reused thereafter.
_DISCOVERED_OPTIONS: tuple[frozenset[str], frozenset[str]] | None = None


_EMPTY_OPTIONS: tuple[frozenset[str], frozenset[str]] = frozenset(), frozenset()


def _parse_parser_actions(parser) -> tuple[set[str], set[str]]:
    """Parse argparse actions into known options and value-taking subsets.

    Inspects `parser._actions` to extract all recognized option strings and
    which ones take values. This is the core parsing logic extracted from
    _discover_comfyui_cli_options() for readability.

    Args:
        parser: An argparse.ArgumentParser instance with configured actions.

    Returns:
        Tuple of (known_options, value_taking_options) as sets.
    """
    known: set[str] = set()
    value_taking: set[str] = set()
    for action in parser._actions:
        for opt in action.option_strings:
            if not opt.startswith("--"):
                continue
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
    return known, value_taking


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

    original_argv = sys.argv
    pre_discovery_modules = set(sys.modules.keys())
    try:
        sys.argv = ["_discover"]
        cli_args_mod = _bootstrap_import("comfy.cli_args")
    except ModuleNotFoundError:
        log.debug("comfy.cli_args not available for option discovery")
        sys.argv = original_argv
        _DISCOVERED_OPTIONS = _EMPTY_OPTIONS
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
        _DISCOVERED_OPTIONS = _EMPTY_OPTIONS
        return _DISCOVERED_OPTIONS

    parser = getattr(cli_args_mod, "parser", None)
    if parser is None:
        log.debug("Could not find parser in comfy.cli_args")
        _DISCOVERED_OPTIONS = _EMPTY_OPTIONS
        return _DISCOVERED_OPTIONS

    known, value_taking = _parse_parser_actions(parser)
    _DISCOVERED_OPTIONS = frozenset(known), frozenset(value_taking)
    return _DISCOVERED_OPTIONS


def _get_base_option(token: str) -> str:
    """Extract base option name from a CLI token.

    Strips inline values from tokens like '--cuda-device=0' to get '--cuda-device'.

    Args:
        token: A CLI argument string (e.g., '--cuda-device=0' or '--cpu').

    Returns:
        Base option name without inline value.
    """
    if "=" in token:
        return token.split("=")[0]
    return token


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
    result = [argv[0]] if argv else []

    i = 1
    while i < len(argv):
        token = argv[i]

        # Skip single-char flags (e.g. -v, -s from test runners)
        if token.startswith("-") and not token.startswith("--"):
            i += 1
            continue

        base = _get_base_option(token)

        if base in known:
            result.append(token)
            # If option takes a value and it's not inline (=), consume next arg
            if base in value_taking and "=" not in token:
                if i + 1 < len(argv):
                    next_token = argv[i + 1]
                    if (
                        next_token.startswith("--")
                        and _get_base_option(next_token) in known
                    ):
                        pass  # Next token is itself a flag — don't consume it
                    elif not next_token.startswith("--"):
                        result.append(next_token)
                        i += 1
        elif token.startswith("--"):
            if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                i += 1
        else:
            result.append(token)
        i += 1
    return result
