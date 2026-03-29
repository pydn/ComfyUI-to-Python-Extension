import json

from .io import load_json_input


def load_workflow_data(workflow: str, input_file: str):
    """Load workflow data from inline JSON or an input file."""
    if input_file:
        return load_json_input(input_file)
    return json.loads(workflow)


def load_frontend_workflow_data(frontend_workflow: str | dict | None):
    """Load optional frontend workflow metadata."""
    if not frontend_workflow:
        return None
    if isinstance(frontend_workflow, str):
        return json.loads(frontend_workflow)
    return frontend_workflow
