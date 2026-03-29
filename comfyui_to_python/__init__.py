from typing import TextIO

from .app import ExportApplication
from .cli import DEFAULT_INPUT_FILE, DEFAULT_OUTPUT_FILE, DEFAULT_QUEUE_SIZE, main
from .node_runtime import get_node_class_mappings, import_custom_nodes


class ComfyUItoPython:
    """Public compatibility facade for the exporter package."""

    def __init__(
        self,
        workflow: str = "",
        frontend_workflow: str | dict | None = None,
        input_file: str = "",
        output_file: str | TextIO = "",
        queue_size: int = 1,
        node_class_mappings: dict | None = None,
        needs_init_custom_nodes: bool = False,
    ):
        self._app = ExportApplication(
            workflow=workflow,
            frontend_workflow=frontend_workflow,
            input_file=input_file,
            output_file=output_file,
            queue_size=queue_size,
            node_class_mappings=node_class_mappings,
            needs_init_custom_nodes=needs_init_custom_nodes,
            node_mapping_loader=get_node_class_mappings,
            custom_node_importer=import_custom_nodes,
        )
        self._app.execute()


def run(
    input_file: str = DEFAULT_INPUT_FILE,
    output_file: str = DEFAULT_OUTPUT_FILE,
    queue_size: int = DEFAULT_QUEUE_SIZE,
) -> None:
    """Generate Python code from a ComfyUI workflow_api.json file."""
    ComfyUItoPython(
        input_file=input_file,
        output_file=output_file,
        queue_size=queue_size,
        needs_init_custom_nodes=True,
    )


__all__ = [
    "ComfyUItoPython",
    "run",
    "main",
    "get_node_class_mappings",
    "import_custom_nodes",
]
