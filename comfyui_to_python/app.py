import copy
import sys

from typing import TextIO

from .generator.planner import WorkflowPlanner
from .generator.render import WorkflowRenderer
from .io import write_python_output
from .load_order import LoadOrderDeterminer
from .workflow_loader import load_frontend_workflow_data, load_workflow_data


class ExportApplication:
    """High-level exporter orchestration."""

    def __init__(
        self,
        workflow: str = "",
        frontend_workflow: str | dict | None = None,
        input_file: str = "",
        output_file: str | TextIO = "",
        queue_size: int = 1,
        node_class_mappings: dict | None = None,
        needs_init_custom_nodes: bool = False,
        node_mapping_loader=None,
        custom_node_importer=None,
    ):
        if input_file and workflow:
            raise ValueError("Can't provide both input_file and workflow")
        if not input_file and not workflow:
            raise ValueError("Needs input_file or workflow")
        if not output_file:
            raise ValueError("Needs output_file")

        self.workflow = workflow
        self.frontend_workflow = frontend_workflow
        self.input_file = input_file
        self.output_file = output_file
        self.queue_size = queue_size
        self.node_mapping_loader = node_mapping_loader
        self.custom_node_importer = custom_node_importer
        self.node_class_mappings = (
            node_class_mappings
            if node_class_mappings is not None
            else self.node_mapping_loader()
        )
        self.needs_init_custom_nodes = needs_init_custom_nodes
        self.base_node_class_mappings = copy.deepcopy(self.node_class_mappings)

    def execute(self) -> None:
        data = load_workflow_data(self.workflow, self.input_file)
        metadata_workflow_data = load_frontend_workflow_data(self.frontend_workflow)

        missing_node_types = {
            node_data["class_type"]
            for node_data in data.values()
            if node_data["class_type"] not in self.node_class_mappings
        }
        if self.needs_init_custom_nodes or missing_node_types:
            self.custom_node_importer()
            # Re-read from the cached "nodes" module in sys.modules after
            # import_custom_nodes() populates it with extras (comfy_extras,
            # custom node directories, etc.). The original dict is a stale copy.
            nodes_mod = sys.modules.get("nodes")
            if nodes_mod is not None:
                fresh_mappings = getattr(nodes_mod, "NODE_CLASS_MAPPINGS", {})
                self.node_class_mappings = fresh_mappings
            # Leave self.base_node_class_mappings unchanged — it represents the
            # pre-custom-node baseline used by WorkflowPlanner to decide whether
            # a node gets a direct import or a NODE_CLASS_MAPPINGS dict lookup.

        load_order = LoadOrderDeterminer(
            data, self.node_class_mappings
        ).determine_load_order()
        plan = WorkflowPlanner(
            self.node_class_mappings, self.base_node_class_mappings
        ).build_plan(
            load_order,
            data,
            metadata_workflow_data,
            queue_size=self.queue_size,
        )
        generated_code = WorkflowRenderer().render(plan)
        write_python_output(self.output_file, generated_code)
        print(f"Code successfully generated and written to {self.output_file}")
