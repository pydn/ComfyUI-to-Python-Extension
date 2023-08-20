import os
from typing import Sequence, Mapping, Any, Union
import sys

sys.path.append('../')


def import_custom_nodes() -> None:
    """Find all custom nodes in the custom_nodes folder and add those node objects to NODE_CLASS_MAPPINGS

    This function sets up a new asyncio event loop, initializes the PromptServer,
    creates a PromptQueue, and initializes the custom nodes.
    """
    import asyncio
    import execution
    from nodes import init_custom_nodes
    import server

    # Creating a new event loop and setting it as the default loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Creating an instance of PromptServer with the loop
    server_instance = server.PromptServer(loop)
    execution.PromptQueue(server_instance)

    # Initializing custom nodes
    init_custom_nodes()

def add_comfyui_directory_to_sys_path() -> None:
    """
    Recursively looks at parent folders starting from the current working directory until it finds 'ComfyUI'.
    Once found, the directory is added to sys.path.
    """
    start_path = os.getcwd()  # Get the current working directory

    def search_directory(path: str) -> None:
        # Check if the current directory contains 'ComfyUI'
        if 'ComfyUI' in os.listdir(path):
            directory_path = os.path.join(path, 'ComfyUI')
            sys.path.append(directory_path)
            print(f"ComfyUI found and added to sys.path: {directory_path}")

        # Get the parent directory
        parent_directory = os.path.dirname(path)

        # If the parent directory is the same as the current directory, we've reached the root and stop the search
        if parent_directory == path:
            return

        # Recursively call the function with the parent directory
        search_directory(parent_directory)

    # Start the search from the current working directory
    search_directory(start_path)


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
        return obj['result'][index]
