import asyncio
import json
import glob
import os
from typing import Sequence, Mapping, Any, Union
import sys

sys.path.append('../')

import execution
from nodes import init_custom_nodes


def read_json_file(file_path: str) -> dict:
    """
    Reads a JSON file and returns its contents as a dictionary.

    Args:
        file_path (str): The path to the JSON file.

    Returns:
        dict: The contents of the JSON file as a dictionary.

    Raises:
        FileNotFoundError: If the file is not found, it lists all JSON files in the directory of the file path.
        ValueError: If the file is not a valid JSON.
    """

    try:
        with open(file_path, 'r') as file:
            data = json.load(file)
        return data

    except FileNotFoundError:
        # Get the directory from the file_path
        directory = os.path.dirname(file_path)

        # If the directory is an empty string (which means file is in the current directory),
        # get the current working directory
        if not directory:
            directory = os.getcwd()

        # Find all JSON files in the directory
        json_files = glob.glob(f"{directory}/*.json")

        # Format the list of JSON files as a string
        json_files_str = "\n".join(json_files)

        raise FileNotFoundError(f"\n\nFile not found: {file_path}. JSON files in the directory:\n{json_files_str}")

    except json.JSONDecodeError:
        raise ValueError(f"Invalid JSON format in file: {file_path}")


def write_code_to_file(filename: str, code: str) -> None:
    """
    Writes given code to a .py file. If the directory does not exist, it creates it.

    Args:
        filename (str): The name of the Python file to save the code to.
        code (str): The code to save.
    """

    # Extract directory from the filename
    directory = os.path.dirname(filename)

    # If the directory does not exist, create it
    if directory and not os.path.exists(directory):
        os.makedirs(directory)

    # Save the code to a .py file
    with open(filename, 'w') as file:
        file.write(code)
        

def import_custom_nodes() -> None:
    """Find all custom nodes in the custom_nodes folder and add those node objects to NODE_CLASS_MAPPINGS

    This function sets up a new asyncio event loop, initializes the PromptServer,
    creates a PromptQueue, and initializes the custom nodes.
    """
    import server

    # Creating a new event loop and setting it as the default loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Creating an instance of PromptServer with the loop
    server_instance = server.PromptServer(loop)
    execution.PromptQueue(server_instance)

    # Initializing custom nodes
    init_custom_nodes()


def add_comfyui_directories_to_sys_path() -> None:
    """
    Recursively looks at parent folders starting from the current working directory until it finds 'ComfyUI' and 'ComfyUI-to-Python-Extension'.
    Once found, the directories are added to sys.path.
    """
    start_path = os.getcwd()  # Get the current working directory

    def search_directory(path: str) -> None:
        # Check if the current directory contains 'ComfyUI' or 'ComfyUI-to-Python-Extension'
        for directory_name in ['ComfyUI', 'ComfyUI-to-Python-Extension']:
            if directory_name in os.listdir(path):
                directory_path = os.path.join(path, directory_name)
                sys.path.append(directory_path)
                print(f"'{directory_name}' found and added to sys.path: {directory_path}")

        # Get the parent directory
        parent_directory = os.path.dirname(path)

        # If the parent directory is the same as the current directory, we've reached the root and stop the search
        if parent_directory == path:
            return

        # Recursively call the function with the parent directory
        search_directory(parent_directory)

    # Start the search from the current working directory
    search_directory(start_path)

# Example usage
add_comfyui_directories_to_sys_path()



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
