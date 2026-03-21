import copy
import inspect
import json
import keyword
import os
import random
import re
import traceback
from argparse import ArgumentParser
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Sequence, TextIO

try:
    import black
except ImportError:
    class _BlackMode:
        pass

    class _BlackFallback:
        Mode = _BlackMode

        @staticmethod
        def format_str(code: str, mode: Any = None) -> str:
            return code

    black = _BlackFallback()

from comfyui_to_python_utils import (
    add_comfyui_directory_to_sys_path,
    add_extra_model_paths,
    find_comfyui_root,
    find_path,
    get_value_at_index,
    import_custom_nodes,
    normalize_path,
)

try:
    add_comfyui_directory_to_sys_path()
    from nodes import NODE_CLASS_MAPPINGS as COMFY_NODE_CLASS_MAPPINGS
except Exception:
    COMFY_NODE_CLASS_MAPPINGS = {}


DEFAULT_INPUT_FILE = "workflow_api.json"
DEFAULT_OUTPUT_FILE = "workflow_api.py"
DEFAULT_QUEUE_SIZE = 10


@dataclass(frozen=True)
class NodeReference:
    node_id: str
    output_index: int = 0


class ExportStageError(Exception):
    def __init__(
        self,
        message: str,
        *,
        stage: str,
        node_id: str | None = None,
        class_type: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.stage = stage
        self.node_id = node_id
        self.class_type = class_type
        self.details = dict(details or {})

    def to_payload(self) -> Dict[str, Any]:
        payload = {
            "error": self.message,
            "stage": self.stage,
            "node_id": self.node_id,
            "class_type": self.class_type,
        }
        payload.update(self.details)
        return {key: value for key, value in payload.items() if value is not None}


@dataclass
class ExportResult:
    code: str
    diagnostics: list[dict[str, Any]]


class FileHandler:
    @staticmethod
    def read_json_file(file_path: str | TextIO, encoding: str = "utf-8") -> dict:
        if hasattr(file_path, "read"):
            return json.load(file_path)
        with open(file_path, "r", encoding=encoding) as file:
            return json.load(file)

    @staticmethod
    def write_code_to_file(file_path: str | TextIO, code: str) -> None:
        if isinstance(file_path, str):
            directory = os.path.dirname(file_path)
            if directory and not os.path.exists(directory):
                os.makedirs(directory)
            with open(file_path, "w", encoding="utf-8") as file:
                file.write(code)
            return
        file_path.write(code)


class IdentifierService:
    def __init__(self) -> None:
        self._seen: Dict[str, int] = {}

    def allocate(self, raw_name: str, *, prefix: str = "value") -> str:
        normalized = self._normalize(raw_name, prefix=prefix)
        count = self._seen.get(normalized, 0) + 1
        self._seen[normalized] = count
        if count == 1:
            return normalized
        return f"{normalized}_{count}"

    @staticmethod
    def _normalize(raw_name: str, *, prefix: str) -> str:
        normalized = (raw_name or "").strip().lower()
        normalized = normalized.replace("-", "_").replace(" ", "_")
        normalized = re.sub(r"\W+", "_", normalized, flags=re.UNICODE).strip("_")
        if not normalized:
            normalized = prefix
        if normalized[0].isdigit():
            normalized = f"{prefix}_{normalized}"
        if keyword.iskeyword(normalized):
            normalized = f"{normalized}_{prefix}"
        return normalized


class WorkflowNormalizer:
    def normalize(self, workflow_data: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
        if not isinstance(workflow_data, Mapping):
            raise ExportStageError(
                "Workflow must be a mapping of node ids to node definitions.",
                stage="ingest",
            )

        normalized_nodes: Dict[str, Dict[str, Any]] = {}
        for raw_node_id, raw_node in workflow_data.items():
            node_id = str(raw_node_id)
            if not isinstance(raw_node, Mapping):
                raise ExportStageError(
                    "Workflow node must be a JSON object.",
                    stage="normalize",
                    node_id=node_id,
                )

            class_type = raw_node.get("class_type")
            if not isinstance(class_type, str) or not class_type.strip():
                raise ExportStageError(
                    "Workflow node is missing a valid class_type.",
                    stage="normalize",
                    node_id=node_id,
                )

            raw_inputs = raw_node.get("inputs", {})
            if raw_inputs is None:
                raw_inputs = {}
            if not isinstance(raw_inputs, Mapping):
                raise ExportStageError(
                    "Workflow node inputs must be a mapping.",
                    stage="normalize",
                    node_id=node_id,
                    class_type=class_type,
                )

            normalized_nodes[node_id] = {
                "node_id": node_id,
                "class_type": class_type.strip(),
                "inputs": {
                    str(input_name): self._normalize_input_value(input_value)
                    for input_name, input_value in raw_inputs.items()
                },
            }
        return normalized_nodes

    def _normalize_input_value(self, value: Any) -> Any:
        if isinstance(value, list):
            reference = self._coerce_reference(value)
            if reference is not None:
                return reference
            return [self._normalize_input_value(item) for item in value]
        if isinstance(value, tuple):
            reference = self._coerce_reference(list(value))
            if reference is not None:
                return reference
            return [self._normalize_input_value(item) for item in value]
        if isinstance(value, Mapping):
            reference = self._coerce_reference(value)
            if reference is not None:
                return reference
            return {
                str(key): self._normalize_input_value(item)
                for key, item in value.items()
            }
        return value

    @staticmethod
    def _coerce_reference(value: Any) -> NodeReference | None:
        if isinstance(value, Mapping):
            node_id = None
            for key in ("node_id", "node", "source", "id"):
                if key in value and isinstance(value[key], (str, int)):
                    node_id = str(value[key])
                    break
            if node_id is None:
                return None
            output_index = value.get("output_index", value.get("output", 0))
            return NodeReference(node_id=node_id, output_index=int(output_index or 0))

        if (
            isinstance(value, Sequence)
            and len(value) >= 2
            and isinstance(value[0], (str, int))
            and isinstance(value[1], int)
        ):
            return NodeReference(node_id=str(value[0]), output_index=int(value[1]))
        return None


def _iter_references(value: Any) -> Iterable[NodeReference]:
    if isinstance(value, NodeReference):
        yield value
        return
    if isinstance(value, list):
        for item in value:
            yield from _iter_references(item)
        return
    if isinstance(value, Mapping):
        for item in value.values():
            yield from _iter_references(item)


def _resolve_node(
    node: Mapping[str, Any],
    node_class_mappings: Mapping[str, Any],
    base_node_class_mappings: Mapping[str, Any],
) -> Dict[str, Any]:
    class_type = node["class_type"]
    if class_type not in node_class_mappings:
        raise ExportStageError(
            "Unsupported node class. Make sure the custom node is installed and loaded in ComfyUI.",
            stage="resolve-node",
            node_id=node["node_id"],
            class_type=class_type,
        )

    class_ctor = node_class_mappings[class_type]
    try:
        class_instance = class_ctor()
    except Exception as exc:
        raise ExportStageError(
            "Failed to initialize node class for export.",
            stage="resolve-node",
            node_id=node["node_id"],
            class_type=class_type,
            details={"exception": str(exc)},
        ) from exc

    function_name = getattr(class_instance, "FUNCTION", None)
    method = getattr(class_instance, function_name, None)
    if not isinstance(function_name, str) or not callable(method):
        raise ExportStageError(
            "Node class FUNCTION is not callable.",
            stage="resolve-node",
            node_id=node["node_id"],
            class_type=class_type,
        )

    input_types = {}
    if hasattr(class_instance, "INPUT_TYPES"):
        input_types = class_instance.INPUT_TYPES() or {}

    signature = inspect.signature(method)
    return {
        "class_instance": class_instance,
        "function_name": function_name,
        "input_types": input_types,
        "function_params": [name for name in signature.parameters if name != "self"],
        "accepts_kwargs": any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        ),
        "is_custom": class_type not in base_node_class_mappings,
    }


def _is_special_node(node: Mapping[str, Any], resolved: Mapping[str, Any]) -> bool:
    class_instance = resolved["class_instance"]
    return (
        getattr(class_instance, "CATEGORY", "") == "loaders"
        or getattr(class_instance, "FUNCTION", "") == "encode"
        or not any(_iter_references(node["inputs"]))
    )


def _determine_load_order(
    nodes: Mapping[str, Dict[str, Any]],
    node_class_mappings: Mapping[str, Any],
    base_node_class_mappings: Mapping[str, Any],
) -> list[tuple[Dict[str, Any], bool]]:
    resolved_cache: Dict[str, Dict[str, Any]] = {}
    visited: Dict[str, str] = {}
    ordered_ids: list[str] = []
    special_ids: list[str] = []

    def resolve_cached(node: Mapping[str, Any]) -> Dict[str, Any]:
        node_id = node["node_id"]
        if node_id not in resolved_cache:
            resolved_cache[node_id] = _resolve_node(
                node, node_class_mappings, base_node_class_mappings
            )
        return resolved_cache[node_id]

    def visit(node_id: str) -> None:
        state = visited.get(node_id)
        if state == "done":
            return
        if state == "visiting":
            raise ExportStageError(
                "Workflow contains a cyclic dependency.",
                stage="dependency",
                node_id=node_id,
            )
        if node_id not in nodes:
            raise ExportStageError(
                "Workflow references a node that is not present.",
                stage="dependency",
                node_id=node_id,
            )

        visited[node_id] = "visiting"
        node = nodes[node_id]
        for reference in _iter_references(node["inputs"]):
            if reference.node_id not in nodes:
                raise ExportStageError(
                    "Workflow input references a missing upstream node.",
                    stage="dependency",
                    node_id=node_id,
                    class_type=node["class_type"],
                    details={"missing_node_id": reference.node_id},
                )
            visit(reference.node_id)

        visited[node_id] = "done"
        ordered_ids.append(node_id)

    for node_id, node in nodes.items():
        resolved = resolve_cached(node)
        if _is_special_node(node, resolved):
            special_ids.append(node_id)
        visit(node_id)

    seen: set[str] = set()
    ordered_nodes: list[tuple[Dict[str, Any], bool]] = []
    for node_id in special_ids + ordered_ids:
        if node_id in seen:
            continue
        ordered_nodes.append((nodes[node_id], node_id in special_ids))
        seen.add(node_id)
    return ordered_nodes


def _render_value(value: Any, output_names: Mapping[str, str]) -> str:
    if value == "__RANDOM_UNIQUE_ID__":
        return "random.randint(1, 2**64)"
    if isinstance(value, NodeReference):
        return f'get_value_at_index({output_names[value.node_id]}, {value.output_index})'
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, list):
        return "[" + ", ".join(_render_value(item, output_names) for item in value) + "]"
    if isinstance(value, tuple):
        return "(" + ", ".join(_render_value(item, output_names) for item in value) + ")"
    if isinstance(value, dict):
        items = ", ".join(
            f"{json.dumps(str(key))}: {_render_value(item, output_names)}"
            for key, item in value.items()
        )
        return "{" + items + "}"
    return repr(value)


def _format_argument(key: str, value: Any, output_names: Mapping[str, str]) -> str:
    if key in {"seed", "noise_seed"}:
        rendered_value = "random.randint(1, 2**64)"
    else:
        rendered_value = _render_value(value, output_names)
    if key.isidentifier() and not keyword.iskeyword(key):
        return f"{key}={rendered_value}"
    return f"**{{{json.dumps(str(key))}: {rendered_value}}}"


def _assemble_python_code(
    *,
    node_plans: list[dict[str, Any]],
    import_names: set[str],
    queue_size: int,
) -> str:
    imports = [
        "import os",
        "import random",
        "import sys",
        "from typing import Any, Mapping, Sequence, Union",
        "import torch",
        "",
        inspect.getsource(get_value_at_index),
        "",
        inspect.getsource(normalize_path),
        "",
        inspect.getsource(find_path),
        "",
        inspect.getsource(find_comfyui_root),
        "",
        inspect.getsource(add_comfyui_directory_to_sys_path),
        "",
        inspect.getsource(add_extra_model_paths),
        "",
        "add_comfyui_directory_to_sys_path()",
        "add_extra_model_paths()",
    ]

    if any(plan["is_custom"] for plan in node_plans):
        imports.extend(["", inspect.getsource(import_custom_nodes), "", "import_custom_nodes()"])

    node_imports = sorted(import_names | {"NODE_CLASS_MAPPINGS"})
    imports.extend(["", f"from nodes import {', '.join(node_imports)}", ""])

    output_names = {plan["node"]["node_id"]: plan["output_name"] for plan in node_plans}
    initialized: set[str] = set()
    initializer_lines: list[str] = []
    special_lines: list[str] = []
    regular_lines: list[str] = []

    for plan in node_plans:
        class_type = plan["node"]["class_type"]
        if class_type not in initialized:
            if plan["is_custom"]:
                initializer_lines.append(
                    f'{plan["initializer_name"]} = NODE_CLASS_MAPPINGS["{class_type}"]()'
                )
            else:
                initializer_lines.append(f'{plan["initializer_name"]} = {class_type}()')
            initialized.add(class_type)

        rendered_inputs = ", ".join(
            _format_argument(key, value, output_names)
            for key, value in plan["inputs"].items()
        )
        target_lines = special_lines if plan["is_special"] else regular_lines
        target_lines.append(
            f'{plan["output_name"]} = {plan["initializer_name"]}.{plan["function_name"]}({rendered_inputs})'
        )

    main_lines = [
        "def main():",
        '    print("Generated by ComfyUI-to-Python-Extension.")',
        "    with torch.inference_mode():",
    ]
    main_lines.extend(f"        {line}" for line in initializer_lines)
    main_lines.extend(f"        {line}" for line in special_lines)
    main_lines.append("")
    main_lines.append(f"        for q in range({queue_size}):")
    if regular_lines:
        main_lines.extend(f"            {line}" for line in regular_lines)
    else:
        main_lines.append("            pass")

    body = "\n".join(imports + main_lines + ["", 'if __name__ == "__main__":', "    main()"])
    return black.format_str(body, mode=black.Mode())


def _build_export(
    *,
    workflow_data: Mapping[str, Any],
    output_file: str | TextIO,
    queue_size: int,
    node_class_mappings: Mapping[str, Any],
    base_node_class_mappings: Mapping[str, Any],
) -> ExportResult:
    nodes = WorkflowNormalizer().normalize(workflow_data)
    ordered_nodes = _determine_load_order(
        nodes, node_class_mappings, base_node_class_mappings
    )

    initializer_names = IdentifierService()
    output_names = IdentifierService()
    initialized_nodes: Dict[str, str] = {}
    import_names: set[str] = set()
    node_plans: list[dict[str, Any]] = []

    for node, is_special in ordered_nodes:
        resolved = _resolve_node(node, node_class_mappings, base_node_class_mappings)
        input_types = resolved["input_types"]
        required_inputs = list((input_types or {}).get("required", {}).keys())
        missing_required = [
            input_name for input_name in required_inputs if input_name not in node["inputs"]
        ]
        if missing_required:
            raise ExportStageError(
                "Workflow node is missing required inputs for export.",
                stage="normalize-inputs",
                node_id=node["node_id"],
                class_type=node["class_type"],
                details={"missing_inputs": missing_required},
            )

        filtered_inputs = dict(node["inputs"])
        if not resolved["accepts_kwargs"]:
            supported_params = set(resolved["function_params"])
            filtered_inputs = {
                key: value
                for key, value in filtered_inputs.items()
                if key in supported_params
            }

        hidden_inputs = (input_types or {}).get("hidden", {})
        supported_params = set(resolved["function_params"])
        if "unique_id" in hidden_inputs and (
            resolved["accepts_kwargs"] or "unique_id" in supported_params
        ):
            filtered_inputs["unique_id"] = "__RANDOM_UNIQUE_ID__"

        class_type = node["class_type"]
        if class_type not in initialized_nodes:
            initialized_nodes[class_type] = initializer_names.allocate(
                class_type, prefix="node"
            )
            if not resolved["is_custom"]:
                import_names.add(class_type)

        node_plans.append(
            {
                "node": node,
                "function_name": resolved["function_name"],
                "initializer_name": initialized_nodes[class_type],
                "output_name": output_names.allocate(
                    f"{class_type}_{node['node_id']}", prefix="result"
                ),
                "inputs": filtered_inputs,
                "is_custom": resolved["is_custom"],
                "is_special": is_special,
            }
        )

    code = _assemble_python_code(
        node_plans=node_plans,
        import_names=import_names,
        queue_size=queue_size,
    )
    FileHandler.write_code_to_file(output_file, code)
    return ExportResult(code=code, diagnostics=[])


class ComfyUItoPython:
    def __init__(
        self,
        workflow: str = "",
        input_file: str = "",
        output_file: str | TextIO = "",
        queue_size: int = 1,
        node_class_mappings: Dict[str, Any] | None = None,
        needs_init_custom_nodes: bool = False,
    ) -> None:
        if input_file and workflow:
            raise ValueError("Can't provide both input_file and workflow")
        if not input_file and not workflow:
            raise ValueError("Needs input_file or workflow")
        if not output_file:
            raise ValueError("Needs output_file")

        self.workflow = workflow
        self.input_file = input_file
        self.output_file = output_file
        self.queue_size = queue_size
        self.needs_init_custom_nodes = needs_init_custom_nodes

        if node_class_mappings is None:
            self.node_class_mappings = dict(COMFY_NODE_CLASS_MAPPINGS)
            self.base_node_class_mappings = dict(COMFY_NODE_CLASS_MAPPINGS)
        else:
            self.node_class_mappings = dict(node_class_mappings)
            self.base_node_class_mappings = {}

        self.result = self.execute()

    def execute(self) -> ExportResult:
        if self.needs_init_custom_nodes:
            built_in_nodes = copy.deepcopy(self.base_node_class_mappings)
            import_custom_nodes()
            try:
                from nodes import NODE_CLASS_MAPPINGS as live_node_class_mappings

                self.node_class_mappings = dict(live_node_class_mappings)
                self.base_node_class_mappings = built_in_nodes
            except Exception:
                pass

        workflow_data = self._read_workflow_data()
        return _build_export(
            workflow_data=workflow_data,
            output_file=self.output_file,
            queue_size=self.queue_size,
            node_class_mappings=self.node_class_mappings,
            base_node_class_mappings=self.base_node_class_mappings,
        )

    def _read_workflow_data(self) -> Mapping[str, Any]:
        try:
            if self.input_file:
                return FileHandler.read_json_file(self.input_file)
            return json.loads(self.workflow)
        except FileNotFoundError as exc:
            raise ExportStageError(
                "Workflow file could not be found.",
                stage="ingest",
                details={"exception": str(exc)},
            ) from exc
        except json.JSONDecodeError as exc:
            raise ExportStageError(
                "Workflow JSON is invalid.",
                stage="ingest",
                details={"exception": str(exc)},
            ) from exc


def export_workflow(
    *,
    workflow: str = "",
    input_file: str = "",
    output_file: str | TextIO,
    queue_size: int = 1,
    node_class_mappings: Dict[str, Any] | None = None,
    needs_init_custom_nodes: bool = False,
) -> ExportResult:
    exporter = ComfyUItoPython(
        workflow=workflow,
        input_file=input_file,
        output_file=output_file,
        queue_size=queue_size,
        node_class_mappings=node_class_mappings,
        needs_init_custom_nodes=needs_init_custom_nodes,
    )
    return exporter.result


def format_export_exception(exc: Exception) -> Dict[str, Any]:
    if isinstance(exc, ExportStageError):
        return exc.to_payload()
    return {
        "error": str(exc),
        "stage": "unexpected",
        "traceback": traceback.format_exc(),
    }


def run(
    input_file: str = DEFAULT_INPUT_FILE,
    output_file: str = DEFAULT_OUTPUT_FILE,
    queue_size: int = DEFAULT_QUEUE_SIZE,
) -> None:
    export_workflow(
        input_file=input_file,
        output_file=output_file,
        queue_size=queue_size,
        needs_init_custom_nodes=True,
    )


def main() -> None:
    parser = ArgumentParser(
        description="Generate Python code from a ComfyUI workflow_api.json file."
    )
    parser.add_argument(
        "-f",
        "--input_file",
        type=str,
        help="path to the input JSON file",
        default=DEFAULT_INPUT_FILE,
    )
    parser.add_argument(
        "-o",
        "--output_file",
        type=str,
        help="path to the output Python file",
        default=DEFAULT_OUTPUT_FILE,
    )
    parser.add_argument(
        "-q",
        "--queue_size",
        type=int,
        help="number of times the workflow will be executed by default",
        default=DEFAULT_QUEUE_SIZE,
    )
    pargs = parser.parse_args()
    try:
        run(**vars(pargs))
        print("Done.")
    except Exception as exc:
        print(json.dumps(format_export_exception(exc), indent=2))
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
