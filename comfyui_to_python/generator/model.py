from dataclasses import dataclass


@dataclass(frozen=True)
class GenerationPlan:
    import_statements: dict[str, set[str]]
    special_functions_code: list[str]
    loop_code: list[str]
    workflow_data: dict
    metadata_workflow_data: dict | None
    queue_size: int
    custom_nodes: bool
