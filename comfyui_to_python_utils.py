import os
import sys
from typing import Any, Mapping, Sequence, Union


def normalize_path(path: str | None) -> str | None:
    if path is None:
        return None
    return os.path.normpath(path.replace("\\", os.sep))


def find_path(name: str, path: str | None = None) -> str | None:
    current_path = normalize_path(path or os.getcwd())
    if current_path is None:
        return None

    try:
        entries = os.listdir(current_path)
    except OSError:
        return None

    if name in entries:
        return os.path.join(current_path, name)

    parent_directory = os.path.dirname(current_path)
    if parent_directory == current_path:
        return None
    return find_path(name, parent_directory)


def find_comfyui_root(path: str | None = None) -> str | None:
    env_override = normalize_path(os.environ.get("COMFYUI_PATH"))
    if env_override and os.path.isdir(env_override):
        return env_override

    current_path = normalize_path(path or os.getcwd())
    if current_path is None:
        return None

    markers = ("main.py", "nodes.py", "folder_paths.py", "execution.py", "server.py")
    try:
        entries = set(os.listdir(current_path))
    except OSError:
        entries = set()

    if all(marker in entries for marker in markers):
        return current_path

    comfyui_child = find_path("ComfyUI", current_path)
    if comfyui_child is not None and os.path.isdir(comfyui_child):
        return normalize_path(comfyui_child)
    return None


def add_comfyui_directory_to_sys_path() -> str:
    comfyui_path = find_comfyui_root()
    if comfyui_path is None or not os.path.isdir(comfyui_path):
        raise RuntimeError(
            "Unable to locate the ComfyUI directory. Run this extension inside a ComfyUI checkout or place it under ComfyUI/custom_nodes."
        )

    normalized_path = normalize_path(comfyui_path)
    if normalized_path in sys.path:
        sys.path.remove(normalized_path)
    sys.path.insert(0, normalized_path)
    return normalized_path


def add_extra_model_paths() -> str | None:
    extra_model_paths = find_path("extra_model_paths.yaml")
    if extra_model_paths is None:
        return None

    load_extra_path_config = None
    import_error_messages: list[str] = []
    for module_name, attr_name in (
        ("utils.extra_config", "load_extra_path_config"),
        ("main", "load_extra_path_config"),
    ):
        try:
            module = __import__(module_name, fromlist=[attr_name])
            load_extra_path_config = getattr(module, attr_name)
            break
        except Exception as exc:
            import_error_messages.append(f"{module_name}: {exc}")

    if load_extra_path_config is None:
        raise RuntimeError(
            "Unable to import ComfyUI extra model path loader. "
            + "; ".join(import_error_messages)
        )

    normalized_path = normalize_path(extra_model_paths)
    load_extra_path_config(normalized_path)
    return normalized_path


def import_custom_nodes() -> None:
    import asyncio

    comfyui_path = add_comfyui_directory_to_sys_path()
    if comfyui_path in sys.path:
        sys.path.remove(comfyui_path)
    sys.path.insert(0, comfyui_path)

    try:
        import execution
        import server
        from nodes import init_extra_nodes
    except Exception as exc:
        raise RuntimeError(
            "Unable to initialize ComfyUI custom nodes for export."
        ) from exc

    loop = asyncio.new_event_loop()
    previous_loop = None
    try:
        previous_loop = asyncio.get_event_loop_policy().get_event_loop()
    except RuntimeError:
        previous_loop = None

    try:
        asyncio.set_event_loop(loop)
        server_instance = server.PromptServer(loop)
        if not hasattr(server_instance, "prompt_queue"):
            execution.PromptQueue(server_instance)

        maybe_coroutine = init_extra_nodes()
        if asyncio.iscoroutine(maybe_coroutine):
            loop.run_until_complete(maybe_coroutine)
    finally:
        asyncio.set_event_loop(previous_loop)
        loop.close()


def get_value_at_index(obj: Union[Sequence, Mapping], index: int) -> Any:
    try:
        return obj[index]
    except KeyError:
        return obj["result"][index]
