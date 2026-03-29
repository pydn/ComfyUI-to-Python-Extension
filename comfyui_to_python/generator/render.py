import inspect
from pprint import pformat
from typing import Any

import black

from ..node_runtime import import_custom_nodes
from .generated_helpers import (
    add_comfyui_directory_to_sys_path,
    add_extra_model_paths,
    bootstrap_comfyui_runtime,
    cleanup_comfyui_runtime,
    find_path,
    get_comfyui_path,
    get_value_at_index,
)
from .model import GenerationPlan


class WorkflowRenderer:
    """Render a generation plan into the final standalone Python source."""

    def render(self, plan: GenerationPlan) -> str:
        workflow_literal = self.format_python_literal(plan.workflow_data)
        if plan.metadata_workflow_data is None:
            extra_pnginfo_literal = "None"
        else:
            extra_pnginfo_literal = self.format_python_literal(
                {"workflow": plan.metadata_workflow_data}
            )

        func_strings = []
        for func in [
            get_value_at_index,
            get_comfyui_path,
            find_path,
            add_comfyui_directory_to_sys_path,
            add_extra_model_paths,
            bootstrap_comfyui_runtime,
            cleanup_comfyui_runtime,
        ]:
            func_strings.append(f"\n{inspect.getsource(func)}")

        static_imports = [
            "# Imports",
            "import json",
            "import os",
            "import random",
            "import sys",
            "from typing import Sequence, Mapping, Any, Union",
        ] + func_strings

        if plan.custom_nodes:
            static_imports.append(f"\n{inspect.getsource(import_custom_nodes)}\n")
            custom_nodes_call = "import_custom_nodes()"
        else:
            custom_nodes_call = None

        imports_code = []
        for module_name in sorted(plan.import_statements.keys()):
            class_names = ", ".join(sorted(plan.import_statements[module_name]))
            imports_code.append(f"from {module_name} import {class_names}")

        workflow_section = [
            "# Workflow data",
            "def build_workflow() -> dict[str, Any]:",
            f"    return {workflow_literal}",
            "",
            "def build_extra_pnginfo() -> dict[str, Any] | None:",
            f"    return {extra_pnginfo_literal}",
            "",
            "workflow = build_workflow()",
            "prompt = json.loads(json.dumps(workflow))",
            "extra_pnginfo = build_extra_pnginfo()",
        ]

        execution_section = [
            "# Workflow execution",
            "def main(unload_models: bool | None = None):",
            "    bootstrap_comfyui_runtime()",
            "    add_extra_model_paths()",
        ]
        if custom_nodes_call:
            execution_section.append(f"    {custom_nodes_call}")
        if imports_code:
            execution_section.extend(["", "    # Node imports"])
            execution_section.extend(f"    {line}" for line in imports_code)
        execution_section.extend(
            [
                "",
                "    import torch",
                "",
                "    try:",
                "        with torch.inference_mode():",
            ]
        )
        execution_section.extend(
            self.build_function_body(
                plan.special_functions_code, "pass", indentation="            "
            ).splitlines()
        )
        execution_section.append(f"            for q in range({plan.queue_size}):")
        execution_section.extend(
            self.build_function_body(
                plan.loop_code, "pass", indentation="                "
            ).splitlines()
        )
        execution_section.extend(
            [
                "    finally:",
                "        cleanup_comfyui_runtime(unload_models=unload_models)",
            ]
        )

        entrypoint_section = [
            "# Entrypoint",
            'if __name__ == "__main__":',
            "    main()",
        ]

        final_code = "\n".join(
            static_imports
            + [""]
            + workflow_section
            + [""]
            + execution_section
            + [""]
            + entrypoint_section
        )
        return black.format_str(final_code, mode=black.Mode())

    @staticmethod
    def format_python_literal(value: Any) -> str:
        return pformat(value, sort_dicts=False)

    @staticmethod
    def build_function_body(
        code_lines: list[str], empty_fallback: str, indentation: str = "    "
    ) -> str:
        if not code_lines:
            return f"{indentation}{empty_fallback}"
        formatted_lines = []
        for line in code_lines:
            stripped_line = line.lstrip()
            if not stripped_line.endswith("\n"):
                stripped_line += "\n"
            formatted_lines.append(f"{indentation}{stripped_line}")
        return "".join(formatted_lines).rstrip()
