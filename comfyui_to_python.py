import copy
import inspect
import json
import keyword
import os
import random
import re
import traceback
from dataclasses import dataclass, field
from argparse import ArgumentParser
from typing import Any, Dict, Iterable, List, Mapping, Sequence, TextIO

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
    find_path,
    find_comfyui_root,
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


@dataclass
class ExportDiagnostic:
    level: str
    message: str
    node_id: str | None = None
    class_type: str | None = None
    stage: str | None = None


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


@dataclass(frozen=True)
class NodeReference:
    node_id: str
    output_index: int = 0


@dataclass
class NormalizedNode:
    node_id: str
    class_type: str
    original_class_type: str
    inputs: Dict[str, Any]
    raw_inputs: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class InvocationPlan:
    node: NormalizedNode
    class_type: str
    function_name: str
    is_custom: bool
    import_name: str | None
    initializer_name: str
    output_name: str
    inputs: Dict[str, Any]
    is_special_function: bool


@dataclass
class ExportResult:
    code: str
    diagnostics: List[ExportDiagnostic]


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
        self._reverse: Dict[str, str] = {}

    def allocate(self, raw_name: str, *, prefix: str = "value") -> str:
        normalized = self._normalize(raw_name, prefix=prefix)
        count = self._seen.get(normalized, 0)
        self._seen[normalized] = count + 1
        final_name = normalized if count == 0 else f"{normalized}_{count + 1}"
        self._reverse[final_name] = raw_name
        return final_name

    def original_for(self, identifier: str) -> str | None:
        return self._reverse.get(identifier)

    @staticmethod
    def _normalize(raw_name: str, *, prefix: str) -> str:
        normalized = (raw_name or "").strip().lower()
        normalized = normalized.replace("-", "_").replace(" ", "_")
        normalized = re.sub(r"\W+", "_", normalized, flags=re.UNICODE)
        normalized = normalized.strip("_")
        if not normalized:
            normalized = prefix
        if normalized[0].isdigit():
            normalized = f"{prefix}_{normalized}"
        if keyword.iskeyword(normalized):
            normalized = f"{normalized}_{prefix}"
        return normalized


class WorkflowNormalizer:
    def normalize(self, workflow_data: Mapping[str, Any]) -> Dict[str, NormalizedNode]:
        if not isinstance(workflow_data, Mapping):
            raise ExportStageError(
                "Workflow must be a mapping of node ids to node definitions.",
                stage="ingest",
            )

        normalized_nodes: Dict[str, NormalizedNode] = {}
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

            canonical_inputs = {
                str(input_name): self._normalize_input_value(input_value)
                for input_name, input_value in raw_inputs.items()
            }
            metadata = {
                "title": raw_node.get("_meta", {}).get("title")
                if isinstance(raw_node.get("_meta"), Mapping)
                else None
            }
            normalized_nodes[node_id] = NormalizedNode(
                node_id=node_id,
                class_type=class_type.strip(),
                original_class_type=class_type,
                inputs=canonical_inputs,
                raw_inputs=dict(raw_inputs),
                metadata=metadata,
            )

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


class LoadOrderResolver:
    def resolve(
        self,
        nodes: Mapping[str, NormalizedNode],
        node_resolver: "NodeResolver",
    ) -> List[tuple[NormalizedNode, bool]]:
        visited: Dict[str, str] = {}
        ordered_node_ids: List[str] = []
        special_node_ids: List[str] = []

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
            for reference in self._iter_references(node.inputs):
                if reference.node_id not in nodes:
                    raise ExportStageError(
                        "Workflow input references a missing upstream node.",
                        stage="dependency",
                        node_id=node.node_id,
                        class_type=node.class_type,
                        details={"missing_node_id": reference.node_id},
                    )
                visit(reference.node_id)

            visited[node_id] = "done"
            ordered_node_ids.append(node_id)

        for node_id, node in nodes.items():
            if self._is_special_function(node, node_resolver):
                special_node_ids.append(node_id)
            visit(node_id)

        seen: set[str] = set()
        ordered: List[tuple[NormalizedNode, bool]] = []
        for node_id in special_node_ids + ordered_node_ids:
            if node_id in seen:
                continue
            ordered.append((nodes[node_id], node_id in special_node_ids))
            seen.add(node_id)
        return ordered

    def _is_special_function(
        self,
        node: NormalizedNode,
        node_resolver: "NodeResolver",
    ) -> bool:
        try:
            resolved = node_resolver.resolve(node)
        except ExportStageError:
            return False
        class_instance = resolved["class_instance"]
        category = getattr(class_instance, "CATEGORY", "")
        function_name = getattr(class_instance, "FUNCTION", "")
        return (
            category == "loaders"
            or function_name == "encode"
            or not any(self._iter_references(node.inputs))
        )

    def _iter_references(self, value: Any) -> Iterable[NodeReference]:
        if isinstance(value, NodeReference):
            yield value
            return
        if isinstance(value, list):
            for item in value:
                yield from self._iter_references(item)
            return
        if isinstance(value, Mapping):
            for item in value.values():
                yield from self._iter_references(item)


class NodeResolver:
    def __init__(
        self,
        node_class_mappings: Mapping[str, Any],
        base_node_class_mappings: Mapping[str, Any],
    ) -> None:
        self.node_class_mappings = dict(node_class_mappings)
        self.base_node_class_mappings = dict(base_node_class_mappings)
        self._cache: Dict[str, Dict[str, Any]] = {}

    def resolve(self, node: NormalizedNode) -> Dict[str, Any]:
        if node.class_type in self._cache:
            return self._cache[node.class_type]

        if node.class_type not in self.node_class_mappings:
            raise ExportStageError(
                "Unsupported node class. Make sure the custom node is installed and loaded in ComfyUI.",
                stage="resolve-node",
                node_id=node.node_id,
                class_type=node.class_type,
            )

        class_ctor = self.node_class_mappings[node.class_type]
        try:
            class_instance = class_ctor()
        except Exception as exc:
            raise ExportStageError(
                "Failed to initialize node class for export.",
                stage="resolve-node",
                node_id=node.node_id,
                class_type=node.class_type,
                details={"exception": str(exc)},
            ) from exc

        function_name = getattr(class_instance, "FUNCTION", None)
        if not isinstance(function_name, str) or not function_name:
            raise ExportStageError(
                "Node class does not expose a callable FUNCTION.",
                stage="resolve-node",
                node_id=node.node_id,
                class_type=node.class_type,
            )

        method = getattr(class_instance, function_name, None)
        if method is None or not callable(method):
            raise ExportStageError(
                "Node class FUNCTION is not callable.",
                stage="resolve-node",
                node_id=node.node_id,
                class_type=node.class_type,
            )

        input_types = {}
        if hasattr(class_instance, "INPUT_TYPES"):
            try:
                input_types = class_instance.INPUT_TYPES() or {}
            except Exception as exc:
                raise ExportStageError(
                    "Failed to inspect node INPUT_TYPES for export.",
                    stage="resolve-node",
                    node_id=node.node_id,
                    class_type=node.class_type,
                    details={"exception": str(exc)},
                ) from exc

        try:
            signature = inspect.signature(method)
        except (TypeError, ValueError) as exc:
            raise ExportStageError(
                "Failed to inspect node function signature.",
                stage="resolve-node",
                node_id=node.node_id,
                class_type=node.class_type,
                details={"exception": str(exc)},
            ) from exc

        accepts_kwargs = any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        )
        params = [
            name
            for name in signature.parameters
            if name != "self"
        ]

        resolved = {
            "class_instance": class_instance,
            "function_name": function_name,
            "input_types": input_types,
            "function_params": params,
            "accepts_kwargs": accepts_kwargs,
            "is_custom": node.class_type not in self.base_node_class_mappings,
        }
        self._cache[node.class_type] = resolved
        return resolved


class InvocationPlanner:
    def __init__(self, node_resolver: NodeResolver) -> None:
        self.node_resolver = node_resolver
        self.object_identifiers = IdentifierService()
        self.output_identifiers = IdentifierService()
        self.import_names: List[str] = []

    def build(self, load_order: Iterable[tuple[NormalizedNode, bool]]) -> List[InvocationPlan]:
        plans: List[InvocationPlan] = []
        initialized_nodes: Dict[str, str] = {}

        for node, is_special_function in load_order:
            resolved = self.node_resolver.resolve(node)
            class_instance = resolved["class_instance"]
            input_types = resolved["input_types"]

            if node.class_type == "PreviewImage":
                continue

            required_inputs = list((input_types or {}).get("required", {}).keys())
            missing_required = [
                input_name for input_name in required_inputs if input_name not in node.inputs
            ]
            if missing_required:
                raise ExportStageError(
                    "Workflow node is missing required inputs for export.",
                    stage="normalize-inputs",
                    node_id=node.node_id,
                    class_type=node.class_type,
                    details={"missing_inputs": missing_required},
                )

            if node.class_type not in initialized_nodes:
                initializer_name = self.object_identifiers.allocate(
                    node.class_type,
                    prefix="node",
                )
                initialized_nodes[node.class_type] = initializer_name
                if not resolved["is_custom"]:
                    self.import_names.append(node.class_type)

            filtered_inputs = self._filter_supported_inputs(node, resolved)
            filtered_inputs = self._apply_hidden_inputs(filtered_inputs, input_types, resolved)

            plans.append(
                InvocationPlan(
                    node=node,
                    class_type=node.class_type,
                    function_name=resolved["function_name"],
                    is_custom=resolved["is_custom"],
                    import_name=node.class_type if not resolved["is_custom"] else None,
                    initializer_name=initialized_nodes[node.class_type],
                    output_name=self.output_identifiers.allocate(
                        f"{node.class_type}_{node.node_id}",
                        prefix="result",
                    ),
                    inputs=filtered_inputs,
                    is_special_function=is_special_function,
                )
            )

        return plans

    def _filter_supported_inputs(
        self,
        node: NormalizedNode,
        resolved: Mapping[str, Any],
    ) -> Dict[str, Any]:
        if resolved["accepts_kwargs"]:
            return dict(node.inputs)

        supported_params = set(resolved["function_params"])
        return {
            key: value
            for key, value in node.inputs.items()
            if key in supported_params
        }

    def _apply_hidden_inputs(
        self,
        inputs: Dict[str, Any],
        input_types: Mapping[str, Any],
        resolved: Mapping[str, Any],
    ) -> Dict[str, Any]:
        hidden_inputs = (input_types or {}).get("hidden", {})
        supported_params = set(resolved["function_params"])

        if "unique_id" in hidden_inputs and (
            resolved["accepts_kwargs"] or "unique_id" in supported_params
        ):
            inputs["unique_id"] = "__RANDOM_UNIQUE_ID__"

        return inputs


class ScriptAssembler:
    def __init__(self, *, mode: str = "embedded") -> None:
        self.mode = mode

    def assemble(
        self,
        *,
        invocation_plans: List[InvocationPlan],
        import_names: List[str],
        queue_size: int,
        diagnostics: List[ExportDiagnostic],
    ) -> str:
        imports = [
            "import os",
            "import random",
            "import sys",
            "from typing import Any, Mapping, Sequence, Union",
            "import torch",
        ]

        warnings_comment = self._build_warning_comment(diagnostics)
        bootstrap_code = self._build_bootstrap(invocation_plans)
        support_comment = self._build_support_table_comment()
        node_imports = self._build_node_imports(import_names)
        initializer_lines = self._build_initializer_lines(invocation_plans)
        special_lines, regular_lines = self._build_invocation_lines(invocation_plans)

        main_lines = [
            "def main():",
            '    print("Generated by ComfyUI-to-Python-Extension.")',
            "    with torch.inference_mode():",
        ]
        if initializer_lines:
            main_lines.extend(f"        {line}" for line in initializer_lines)
        if special_lines:
            main_lines.extend(f"        {line}" for line in special_lines)
        main_lines.append("")
        main_lines.append(f"        for q in range({queue_size}):")
        if regular_lines:
            main_lines.extend(f"            {line}" for line in regular_lines)
        else:
            main_lines.append("            pass")

        body = "\n".join(
            imports
            + [""]
            + warnings_comment
            + support_comment
            + [""]
            + bootstrap_code
            + [""]
            + node_imports
            + [""]
            + main_lines
            + ["", 'if __name__ == "__main__":', "    main()"]
        )

        return black.format_str(body, mode=black.Mode())

    def _build_warning_comment(
        self,
        diagnostics: List[ExportDiagnostic],
    ) -> List[str]:
        lines = [
            "# Export warnings:",
            "# - Generated scripts may not preserve ComfyUI cache behavior exactly.",
            "# - Prompt metadata and extra PNG info may differ from the WebUI runtime.",
            "# - Unsupported custom nodes will fail at export time with a structured error.",
        ]
        for diagnostic in diagnostics:
            if diagnostic.level == "warning":
                lines.append(f"# - {diagnostic.message}")
        return lines

    def _build_support_table_comment(self) -> List[str]:
        return [
            "# Support table:",
            "# - fully supported: built-in nodes and custom nodes present in NODE_CLASS_MAPPINGS",
            "# - exports with warnings: runtime metadata and cache-sensitive workflows",
            "# - unsupported: node classes missing from the active ComfyUI environment",
        ]

    def _build_bootstrap(self, invocation_plans: List[InvocationPlan]) -> List[str]:
        needs_custom_nodes = any(plan.is_custom for plan in invocation_plans)
        if self.mode == "portable":
            lines = [
                "def bootstrap_environment():",
                "    add_comfyui_directory_to_sys_path()",
                "    add_extra_model_paths()",
            ]
            if needs_custom_nodes:
                lines.append("    import_custom_nodes()")
            lines.extend(["", "bootstrap_environment()"])
            return lines

        lines = [
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
        if needs_custom_nodes:
            lines.extend(["", inspect.getsource(import_custom_nodes), "", "import_custom_nodes()"])
        return lines

    def _build_node_imports(self, import_names: List[str]) -> List[str]:
        unique_names = sorted(set(import_names) | {"NODE_CLASS_MAPPINGS"})
        return [f"from nodes import {', '.join(unique_names)}"]

    def _build_initializer_lines(
        self,
        invocation_plans: List[InvocationPlan],
    ) -> List[str]:
        initialized: Dict[str, str] = {}
        lines: List[str] = []
        for plan in invocation_plans:
            if plan.class_type in initialized:
                continue
            initialized[plan.class_type] = plan.initializer_name
            if plan.is_custom:
                lines.append(
                    f'{plan.initializer_name} = NODE_CLASS_MAPPINGS["{plan.class_type}"]()'
                )
            else:
                lines.append(f"{plan.initializer_name} = {plan.class_type}()")
        return lines

    def _build_invocation_lines(
        self,
        invocation_plans: List[InvocationPlan],
    ) -> tuple[List[str], List[str]]:
        output_lookup = {
            plan.node.node_id: plan.output_name
            for plan in invocation_plans
        }
        special_lines: List[str] = []
        regular_lines: List[str] = []
        for plan in invocation_plans:
            rendered_inputs = ", ".join(
                self._format_argument(key, value, output_lookup)
                for key, value in plan.inputs.items()
            )
            call = (
                f"{plan.output_name} = "
                f"{plan.initializer_name}.{plan.function_name}({rendered_inputs})"
            )
            target = special_lines if plan.is_special_function else regular_lines
            target.append(call)
        return special_lines, regular_lines

    def _format_argument(
        self,
        key: str,
        value: Any,
        output_lookup: Mapping[str, str],
    ) -> str:
        rendered_value = self._render_value(value, output_lookup)
        if self._is_safe_keyword_argument(key):
            return f"{key}={rendered_value}"
        return f"**{{{json.dumps(str(key))}: {rendered_value}}}"

    @staticmethod
    def _is_safe_keyword_argument(key: str) -> bool:
        return key.isidentifier() and not keyword.iskeyword(key)

    def _render_value(
        self,
        value: Any,
        output_lookup: Mapping[str, str],
    ) -> str:
        if value == "__RANDOM_UNIQUE_ID__":
            return "random.randint(1, 2**64)"
        if isinstance(value, NodeReference):
            return (
                f'get_value_at_index({output_lookup[value.node_id]}, {value.output_index})'
            )
        if isinstance(value, str):
            if value in {"__RANDOM_SEED__", "__RANDOM_NOISE_SEED__"}:
                return "random.randint(1, 2**64)"
            return json.dumps(value)
        if isinstance(value, list):
            return "[" + ", ".join(self._render_value(item, output_lookup) for item in value) + "]"
        if isinstance(value, tuple):
            return "(" + ", ".join(self._render_value(item, output_lookup) for item in value) + ")"
        if isinstance(value, dict):
            items = ", ".join(
                f"{json.dumps(str(key))}: {self._render_value(item, output_lookup)}"
                for key, item in value.items()
            )
            return "{" + items + "}"
        return repr(value)


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
        self.node_class_mappings = dict(node_class_mappings or COMFY_NODE_CLASS_MAPPINGS)
        self.needs_init_custom_nodes = needs_init_custom_nodes
        self.base_node_class_mappings = copy.deepcopy(self.node_class_mappings)
        self.result = self.execute()

    def execute(self) -> ExportResult:
        if self.needs_init_custom_nodes:
            import_custom_nodes()
            if not self.node_class_mappings:
                try:
                    from nodes import NODE_CLASS_MAPPINGS as live_node_mappings

                    self.node_class_mappings = dict(live_node_mappings)
                    self.base_node_class_mappings = dict(live_node_mappings)
                except Exception:
                    pass
        elif self.node_class_mappings:
            self.base_node_class_mappings = {}

        workflow_data = self._read_workflow_data()
        diagnostics = [
            ExportDiagnostic(
                level="warning",
                message="Portable script mode is scaffolded internally but embedded mode remains the default.",
                stage="assemble",
            )
        ]
        normalizer = WorkflowNormalizer()
        normalized_nodes = normalizer.normalize(workflow_data)
        node_resolver = NodeResolver(
            self.node_class_mappings,
            self.base_node_class_mappings,
        )
        load_order = LoadOrderResolver().resolve(normalized_nodes, node_resolver)
        invocation_planner = InvocationPlanner(node_resolver)
        invocation_plans = invocation_planner.build(load_order)
        code = ScriptAssembler(mode="embedded").assemble(
            invocation_plans=invocation_plans,
            import_names=invocation_planner.import_names,
            queue_size=self.queue_size,
            diagnostics=diagnostics,
        )
        FileHandler.write_code_to_file(self.output_file, code)
        return ExportResult(code=code, diagnostics=diagnostics)

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
