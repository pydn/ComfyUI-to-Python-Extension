import inspect
import json
import keyword
import random
import re
from typing import Any, Callable

from .model import GenerationPlan


class WorkflowPlanner:
    """Convert ordered workflow nodes into a renderer-ready generation plan."""

    def __init__(self, node_class_mappings: dict, base_node_class_mappings: dict):
        self.node_class_mappings = node_class_mappings
        self.base_node_class_mappings = base_node_class_mappings

    @staticmethod
    def sanitize_node_id(node_id: str) -> str:
        sanitized = re.sub(r"[^a-z0-9_]", "_", str(node_id).lower().strip())
        sanitized = re.sub(r"_+", "_", sanitized).strip("_")
        if not sanitized:
            sanitized = "node"
        return sanitized

    @staticmethod
    def clean_variable_name(class_type: str) -> str:
        clean_name = class_type.lower().strip().replace("-", "_").replace(" ", "_")
        clean_name = re.sub(r"[^a-z0-9_]", "", clean_name)
        if clean_name[0].isdigit():
            clean_name = "_" + clean_name
        return clean_name

    def build_plan(
        self,
        load_order: list[tuple[str, dict, bool]],
        workflow_data: dict,
        metadata_workflow_data: dict | None = None,
        queue_size: int = 10,
    ) -> GenerationPlan:
        import_statements = {"nodes": {"NODE_CLASS_MAPPINGS"}}
        executed_variables = {}
        special_functions_code = []
        code = []
        initialized_objects = {}
        custom_nodes = False

        for idx, data, is_special_function in load_order:
            inputs, class_type = data["inputs"], data["class_type"]
            input_types = self.node_class_mappings[class_type].INPUT_TYPES()
            input_value_types = self.get_input_value_types(input_types)
            class_def = self.node_class_mappings[class_type]()

            missing_required_variable = False
            if "required" in input_types.keys():
                for required in input_types["required"]:
                    if required not in inputs.keys():
                        missing_required_variable = True
            if missing_required_variable:
                continue

            if class_type not in initialized_objects:
                if class_type == "PreviewImage":
                    continue

                class_type, import_statement, class_code = self.get_class_info(
                    class_type
                )
                initialized_objects[class_type] = self.clean_variable_name(class_type)
                if class_type in self.base_node_class_mappings.keys():
                    module_name, import_name = import_statement
                    import_statements.setdefault(module_name, set()).add(import_name)
                if 'NODE_CLASS_MAPPINGS["' in class_code:
                    custom_nodes = True
                special_functions_code.append(class_code)

            is_v3_node = self.is_v3_node(class_def)

            if is_v3_node:
                # v3 (comfy_api.io.ComfyNode) nodes run through EXECUTE_NORMALIZED, which forwards **kwargs verbatim: there is no stable signature to filter inputs against, and hidden inputs are not execute() kwargs at all — the executor injects them via PREPARE_CLASS_CLONE.
                func_name = getattr(class_def, "FUNCTION", "EXECUTE_NORMALIZED")
                if func_name == "EXECUTE_NORMALIZED_ASYNC":
                    raise ValueError(
                        f"Node '{class_type}' (id {idx}) uses an async v3 execute() "
                        "(EXECUTE_NORMALIZED_ASYNC); the generated script is synchronous."
                    )
                # Do not mutate the workflow data: build_workflow() renders it verbatim.
                inputs = dict(inputs)

            else:
                class_def_params = self.get_function_parameters(
                    getattr(class_def, class_def.FUNCTION)
                )
                no_params = class_def_params is None

                inputs = {
                    key: value
                    for key, value in inputs.items()
                    if no_params or key in class_def_params
                }

                hidden_inputs = input_types.get("hidden", {})
                if (
                    "unique_id" in hidden_inputs
                    and (no_params or "unique_id" in class_def_params)
                ):
                    inputs["unique_id"] = random.randint(1, 2**64)
                if "prompt" in hidden_inputs and (no_params or "prompt" in class_def_params):
                    inputs["prompt"] = {"variable_name": "prompt"}
                if "extra_pnginfo" in hidden_inputs and (
                    no_params or "extra_pnginfo" in class_def_params
                ):
                    inputs["extra_pnginfo"] = {"variable_name": "extra_pnginfo"}
                if "hidden" not in input_types and class_def_params is not None:
                    if "unique_id" in class_def_params:
                        inputs["unique_id"] = random.randint(1, 2**64)

            executed_variables[idx] = (
                f"{self.clean_variable_name(class_type)}_"
                f"{self.sanitize_node_id(str(idx))}"
            )
            inputs = self.update_inputs(inputs, executed_variables)

            v3_hidden_inputs: str | None = None
            if is_v3_node:
                inputs, v3_hidden_inputs = self.prepare_v3_node_call(
                    class_type, class_def, inputs, input_types.get("hidden", {}) or {}
                )

            seed_sync_code = self.create_prompt_seed_sync_code(
                idx, inputs, input_value_types, is_special_function
            )

            target_lines = special_functions_code if is_special_function else code
            if seed_sync_code:
                target_lines.extend(seed_sync_code)
            target_lines.append(
                self.create_function_call_code(
                    initialized_objects[class_type],
                    class_def.FUNCTION,
                    executed_variables[idx],
                    is_special_function,
                    input_value_types=input_value_types,
                    v3_hidden_inputs=v3_hidden_inputs,
                    **inputs,
                )
            )

        return GenerationPlan(
            import_statements=import_statements,
            special_functions_code=special_functions_code,
            loop_code=code,
            workflow_data=workflow_data,
            metadata_workflow_data=metadata_workflow_data,
            queue_size=queue_size,
            custom_nodes=custom_nodes,
        )

    def create_function_call_code(
        self,
        obj_name: str,
        func: str,
        variable_name: str,
        is_special_function: bool,
        input_value_types: dict[str, str] | None = None,
        v3_hidden_inputs: str | None = None,  # PREPARE_CLASS_CLONE payload body; None for v1 nodes
        **kwargs,
    ) -> str:
        args = ", ".join(
            self.format_arg(key, value, (input_value_types or {}).get(key))
            for key, value in kwargs.items()
        )
        if v3_hidden_inputs is not None:
            # The executor prepares a shallow class clone per v3 node so hidden inputs are reachable via cls.hidden; mirror that here. HiddenHolder resolves any omitted key (e.g. UNIQUE_ID in a headless script) to None.
            receiver = f"type({obj_name}).PREPARE_CLASS_CLONE({{{v3_hidden_inputs}}}).{func}"
        else:
            receiver = f"{obj_name}.{func}"
        code = f"{variable_name} = {receiver}({args})\n"
        if not is_special_function:
            code = f"\t{code}"
        return code

    def create_prompt_seed_sync_code(
        self,
        node_id: str,
        inputs: dict,
        input_value_types: dict[str, str],
        is_special_function: bool,
    ) -> list[str]:
        seed_sync_lines = []
        for key in ("seed", "noise_seed"):
            if key not in inputs:
                continue
            randomized_seed_variable = (
                f"node_{self.sanitize_node_id(str(node_id))}_{self.clean_variable_name(key)}"
            )
            randomized_seed_code = self.get_randomized_seed_code(
                input_value_types.get(key)
            )
            seed_sync_lines.append(
                f'{randomized_seed_variable} = prompt["{node_id}"]["inputs"]["{key}"] = {randomized_seed_code}'
            )
            inputs[key] = {"variable_name": randomized_seed_variable}

        if not seed_sync_lines:
            return []

        indentation = "" if is_special_function else "\t"
        return [f"{indentation}{line}\n" for line in seed_sync_lines]

    def format_arg(self, key: str, value: Any, input_value_type: str | None = None) -> str:
        value_code = self.format_arg_value(key, value, input_value_type)
        if key.isidentifier() and not keyword.iskeyword(key):
            return f"{key}={value_code}"
        return f"**{{{json.dumps(key)}: {value_code}}}"

    @staticmethod
    def format_arg_value(
        key: str, value: Any, input_value_type: str | None = None
    ) -> str:
        if isinstance(value, dict) and "variable_name" in value:
            return value["variable_name"]
        if key == "noise_seed" or key == "seed":
            return WorkflowPlanner.get_randomized_seed_code(input_value_type)
        if isinstance(value, str):
            return json.dumps(value)
        if isinstance(value, (list, dict)):  # folded v3 dynamic input or DICT-widget value derived from the prompt
            return WorkflowPlanner.format_structured_value(value)
        return repr(value)

    @staticmethod
    def format_structured_value(value: Any) -> str:
        """Render a prompt-derived literal (str/int/float/bool/None/list/dict) as Python source."""
        if isinstance(value, dict):
            if len(value) == 1 and "variable_name" in value:  # resolved link placeholder from update_inputs()
                return value["variable_name"]
            items = ", ".join(
                f"{json.dumps(item_key)}: {WorkflowPlanner.format_structured_value(item_value)}"
                for item_key, item_value in value.items()
            )
            return f"{{{items}}}"
        if isinstance(value, list):
            return (
                "[" + ", ".join(WorkflowPlanner.format_structured_value(item) for item in value) + "]"
            )
        if isinstance(value, str):
            return json.dumps(value)
        return repr(value)

    @staticmethod
    def get_input_value_types(input_types: dict) -> dict[str, str]:
        value_types = {}
        for section in ("required", "optional", "hidden"):
            for key, value in input_types.get(section, {}).items():
                if isinstance(value, tuple) and value:
                    value_types[key] = value[0]
                elif isinstance(value, str):
                    value_types[key] = value
        return value_types

    @staticmethod
    def get_randomized_seed_code(input_value_type: str | None) -> str:
        randomized_seed_code = "random.randint(1, 2**64)"
        if input_value_type == "STRING":
            return f"str({randomized_seed_code})"
        return randomized_seed_code

    def get_class_info(self, class_type: str) -> tuple[str, tuple[str, str], str]:
        class_obj = self.base_node_class_mappings.get(class_type)
        module_name = "nodes"
        if class_obj is not None:
            module_name = class_obj.__module__
        variable_name = self.clean_variable_name(class_type)
        is_importable_module = bool(
            module_name
            and "/" not in module_name
            and "\\" not in module_name
            and all(part.isidentifier() for part in module_name.split("."))
        )
        if class_type in self.base_node_class_mappings.keys() and is_importable_module:
            import_statement = (module_name, class_type)
            class_code = f"{variable_name} = {class_type.strip()}()"
        else:
            import_statement = ("nodes", "NODE_CLASS_MAPPINGS")
            class_code = f'{variable_name} = NODE_CLASS_MAPPINGS["{class_type}"]()'
        return class_type, import_statement, class_code

    @staticmethod
    def get_function_parameters(func: Callable) -> list | None:
        signature = inspect.signature(func)
        parameters = {
            name: param.default if param.default != param.empty else None
            for name, param in signature.parameters.items()
        }
        catch_all = any(
            param.kind == inspect.Parameter.VAR_KEYWORD
            for param in signature.parameters.values()
        )
        return list(parameters.keys()) if not catch_all else None

    @staticmethod
    def is_v3_node(class_def: Any) -> bool:
        """Detect v3 nodes (comfy_api.io.ComfyNode) via their normalized execution entry points."""
        function = getattr(class_def, "FUNCTION", None)
        return function in ("EXECUTE_NORMALIZED", "EXECUTE_NORMALIZED_ASYNC") or hasattr(
            class_def, "EXECUTE_NORMALIZED"
        )

    def prepare_v3_node_call(
        self, class_type: str, class_def: Any, inputs: dict, declared_hidden: dict
    ) -> tuple[dict[str, Any], str]:
        """Prepare v3 node inputs the same way ``comfy_execution.get_input_data`` does.

        - ``get_finalized_class_inputs`` expands dynamic schema entries (e.g. DynamicCombo)
          against the live prompt keys, producing the dotted ids like
          ``"resize_type"`` / ``"resize_type.shorter_size"`` plus their fold paths.
        - ``build_nested_inputs`` folds those dotted prompt keys into the single nested-dict
          kwarg that v3 ``execute()`` actually receives, e.g.
          ``resize_type={"resize_type": "scale shorter dimension", "shorter_size": 1080}``.
        - Hidden inputs are carried in the PREPARE_CLASS_CLONE payload instead of kwargs.
          UNIQUE_ID and DYNPROMPT are intentionally omitted: a headless script has no server
          context, so they resolve to None (e.g. skips progress-text paths).
        """
        try:
            from comfy_api.latest import _io as comfy_io
        except ImportError as exc:  # pragma: no cover - v3 schema expansion needs a ComfyUI runtime on sys.path
            raise RuntimeError(
                f"Node '{class_type}' is a v3 (comfy_api.io.ComfyNode) node; its inputs "
                "can only be converted while running inside a ComfyUI installation."
            ) from exc

        valid_inputs = class_def.INPUT_TYPES()
        finalized, _hidden, v3_data = comfy_io.get_finalized_class_inputs(
            valid_inputs, inputs
        )

        known_keys = (
            set(finalized.get("required", {})) | set(finalized.get("optional", {}))
        )
        accept_all_inputs = bool(getattr(class_def, "ACCEPT_ALL_INPUTS", False))

        folded = comfy_io.build_nested_inputs(dict(inputs), v3_data)
        result: dict[str, Any] = {}
        for key, value in folded.items():
            # Drop stale dotted keys (e.g. option inputs of an unselected DynamicCombo): the executor never receives them either.
            if accept_all_inputs or key in known_keys:
                result[key] = value

        hidden_parts: list[str] = []
        if "prompt" in declared_hidden:
            hidden_parts.append('"PROMPT": prompt')
        if "extra_pnginfo" in declared_hidden:
            hidden_parts.append('"EXTRA_PNGINFO": extra_pnginfo')

        return result, ", ".join(hidden_parts)

    def update_inputs(self, inputs: dict, executed_variables: dict) -> dict:
        for key in inputs.keys():
            if (
                isinstance(inputs[key], list)
                and inputs[key][0] in executed_variables.keys()
            ):
                inputs[key] = {
                    "variable_name": f"get_value_at_index({executed_variables[inputs[key][0]]}, {inputs[key][1]})"
                }
        return inputs
