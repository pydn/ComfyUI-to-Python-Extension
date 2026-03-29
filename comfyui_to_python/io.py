import json
import os
from typing import TextIO


def load_json_input(file_path: str | TextIO, encoding: str = "utf-8") -> dict:
    """Read workflow JSON from a file path or file-like object."""
    if hasattr(file_path, "read"):
        return json.load(file_path)
    with open(file_path, "r", encoding=encoding) as file:
        return json.load(file)


def write_python_output(file_path: str | TextIO, code: str) -> None:
    """Write generated Python to a file path or file-like object."""
    if isinstance(file_path, str):
        directory = os.path.dirname(file_path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory)
        with open(file_path, "w", encoding="utf-8") as file:
            file.write(code)
        return
    file_path.write(code)
