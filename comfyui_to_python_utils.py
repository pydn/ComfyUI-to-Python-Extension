import os
from typing import Sequence, Mapping, Any, Union
import sys


def normalize_path(path: str | None) -> str | None:
    """Normalize a path while tolerating Windows-style separators in test and portable setups."""
    if path is None:
        return None
    return os.path.normpath(path.replace("\\", os.sep))


def import_custom_nodes() -> None:
    """Find all custom nodes in the custom_nodes folder and add those node objects to NODE_CLASS_MAPPINGS

    This function sets up a new asyncio event loop, initializes the PromptServer,
    creates a PromptQueue, and initializes the custom nodes.
    """
    import asyncio
    import execution
    from nodes import init_extra_nodes
    import server

    comfyui_path = add_comfyui_directory_to_sys_path()
    if comfyui_path in sys.path:
        sys.path.remove(comfyui_path)
    sys.path.insert(0, comfyui_path)

    # Creating a new event loop and setting it as the default loop
    loop = asyncio.new_event_loop()
    previous_loop = None
    try:
        previous_loop = asyncio.get_event_loop_policy().get_event_loop()
    except RuntimeError:
        previous_loop = None
    asyncio.set_event_loop(loop)

    try:
        # Creating an instance of PromptServer with the loop
        server_instance = server.PromptServer(loop)
        if not hasattr(server_instance, "prompt_queue"):
            execution.PromptQueue(server_instance)

        # Initializing custom nodes
        maybe_coroutine = init_extra_nodes()
        if asyncio.iscoroutine(maybe_coroutine):
            loop.run_until_complete(maybe_coroutine)
    finally:
        asyncio.set_event_loop(previous_loop)
        loop.close()


def find_path(name: str, path: str = None) -> str:
    """
    Recursively looks at parent folders starting from the given path until it finds the given name.
    Returns the path as a Path object if found, or None otherwise.
    """
    # If no path is given, use the current working directory
    if path is None:
        path = os.getcwd()

    path = normalize_path(path)

    # Check if the current directory contains the name
    try:
        if name in os.listdir(path):
            path_name = os.path.join(path, name)
            return path_name
    except OSError:
        return None

    # Get the parent directory
    parent_directory = os.path.dirname(path)

    # If the parent directory is the same as the current directory, we've reached the root and stop the search
    if parent_directory == path:
        return None

    # Recursively call the function with the parent directory
    return find_path(name, parent_directory)


def find_comfyui_root(path: str = None) -> str:
    """Locate the ComfyUI root, preferring COMFYUI_PATH when provided."""
    env_path = normalize_path(os.environ.get("COMFYUI_PATH"))
    if env_path is not None and os.path.isdir(env_path):
        return env_path

    if path is None:
        path = os.getcwd()

    path = normalize_path(path)
    try:
        entries = set(os.listdir(path))
    except OSError:
        entries = set()

    markers = {"main.py", "nodes.py", "folder_paths.py", "execution.py", "server.py"}
    if markers.issubset(entries):
        return path

    comfyui_path = find_path("ComfyUI", path)
    if comfyui_path is not None and os.path.isdir(comfyui_path):
        return normalize_path(comfyui_path)
    return None


def add_comfyui_directory_to_sys_path() -> str:
    """
    Add 'ComfyUI' to the sys.path
    """
    comfyui_path = find_comfyui_root()
    if comfyui_path is not None and os.path.isdir(comfyui_path):
        if comfyui_path in sys.path:
            sys.path.remove(comfyui_path)
        sys.path.insert(0, comfyui_path)
        return comfyui_path
    raise RuntimeError(
        "Unable to locate the ComfyUI directory. Run this extension inside a ComfyUI checkout or place it under ComfyUI/custom_nodes."
    )


def add_extra_model_paths() -> str | None:
    """
    Parse the optional extra_model_paths.yaml file and add the parsed paths to the sys.path.
    """
    extra_model_paths = find_path("extra_model_paths.yaml")

    if extra_model_paths is None:
        return None

    # Newer ComfyUI versions expose the loader under utils.extra_config, but older checkouts still use main.py.
    try:
        from utils.extra_config import load_extra_path_config
    except ImportError:
        from main import load_extra_path_config

    extra_model_paths = normalize_path(extra_model_paths)
    load_extra_path_config(extra_model_paths)
    return extra_model_paths


def get_value_at_index(obj: Union[Sequence, Mapping], index: int) -> Any:
    """Returns the value at the given index of a sequence or mapping.

    If the object is a sequence (like list or string), returns the value at the given index.
    If the object is a mapping (like a dictionary), returns the value at the index-th key.

    Some return a dictionary, in these cases, we look for the "results" key

    Args:
        obj (Union[Sequence, Mapping]): The object to retrieve the value from.
        index (int): The index of the value to retrieve.

    Returns:
        Any: The value at the given index.

    Raises:
        IndexError: If the index is out of bounds for the object and the object is not a mapping.
    """
    try:
        return obj[index]
    except KeyError:
        return obj["result"][index]
