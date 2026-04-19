from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class GenerationPlan:
    import_statements: dict[str, set[str]]
    special_functions_code: list[str]
    loop_code: list[str]
    workflow_data: dict
    metadata_workflow_data: dict | None
    queue_size: int
    custom_nodes: bool
    execution_mode: Literal["oneshot", "session"] = field(default="oneshot")
    executed_variables: dict[str, str] = field(default_factory=dict)
