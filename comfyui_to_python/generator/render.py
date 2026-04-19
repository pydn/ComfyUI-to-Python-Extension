import inspect
import threading
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

    def __init__(self, execution_mode: str = "oneshot"):
        self.execution_mode = execution_mode

    def render(self, plan: GenerationPlan) -> str:
        if self.execution_mode == "session":
            return self._render_session_mode(plan)
        return self._render_oneshot_mode(plan)

    # ── shared sections ──────────────────────────────────────────────

    @staticmethod
    def _build_entrypoint_section() -> list[str]:
        return [
            "# Entrypoint",
            'if __name__ == "__main__":',
            "    main()",
        ]

    def _build_imports_section(self, plan: GenerationPlan) -> list[str]:
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
            "import threading",
            "from typing import Sequence, Mapping, Any, Union",
        ] + func_strings

        static_imports.append(f"\n{inspect.getsource(import_custom_nodes)}\n")

        return static_imports

    def _build_workflow_section(self, plan: GenerationPlan) -> list[str]:
        workflow_literal = self.format_python_literal(plan.workflow_data)
        if plan.metadata_workflow_data is None:
            extra_pnginfo_literal = "None"
        else:
            extra_pnginfo_literal = self.format_python_literal(
                {"workflow": plan.metadata_workflow_data}
            )

        return [
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

    # ── oneshot renderer ─────────────────────────────────────────────

    def _render_oneshot_mode(self, plan: GenerationPlan) -> str:
        imports_section = self._build_imports_section(plan)
        workflow_section = self._build_workflow_section(plan)
        execution_section = self._build_execution_section(plan)
        entrypoint_section = self._build_entrypoint_section()

        final_code = "\n".join(
            imports_section
            + [""]
            + workflow_section
            + [""]
            + execution_section
            + [""]
            + entrypoint_section
        )
        return black.format_str(final_code, mode=black.Mode())

    def _build_execution_section(self, plan: GenerationPlan) -> list[str]:
        imports_code = self._build_node_imports(plan.import_statements)

        lines = [
            "# Workflow execution",
            "def main(unload_models: bool | None = None):",
            "    bootstrap_comfyui_runtime()",
            "    add_extra_model_paths()",
        ]
        if plan.custom_nodes:
            lines.append("    import_custom_nodes()")
        if imports_code:
            lines.extend(["", "    # Node imports"])
            lines.extend(f"    {line}" for line in imports_code)
        lines.extend(
            [
                "",
                "    import torch",
                "",
                "    try:",
                "        with torch.inference_mode():",
            ]
        )
        lines.extend(
            self.build_function_body(
                plan.special_functions_code, "pass", indentation="            "
            ).splitlines()
        )
        lines.append(f"            for q in range({plan.queue_size}):")
        lines.extend(
            self.build_function_body(
                plan.loop_code, "pass", indentation="                "
            ).splitlines()
        )
        lines.extend(
            [
                "    finally:",
                "        cleanup_comfyui_runtime(unload_models=unload_models)",
            ]
        )
        return lines

    @staticmethod
    def _build_node_imports(
        import_statements: dict[str, set[str]],
    ) -> list[str]:
        imports_code = []
        for module_name in sorted(import_statements.keys()):
            class_names = ", ".join(sorted(import_statements[module_name]))
            imports_code.append(f"from {module_name} import {class_names}")
        return imports_code

    # ── session renderer ─────────────────────────────────────────────

    def _render_session_mode(self, plan: GenerationPlan) -> str:
        imports_section = self._build_imports_section(plan)
        workflow_section = self._build_workflow_section(plan)
        session_class = self._build_session_class(plan)
        main_wrapper = self._build_main_wrapper(plan)
        entrypoint_section = self._build_entrypoint_section()

        final_code = "\n".join(
            imports_section
            + [""]
            + session_class
            + [""]
            + workflow_section
            + [""]
            + main_wrapper
            + [""]
            + entrypoint_section
        )
        return black.format_str(final_code, mode=black.Mode())

    def _build_session_class(self, plan: GenerationPlan) -> list[str]:
        node_imports = self._build_node_imports(plan.import_statements)
        node_import_lines = []
        if node_imports:
            node_import_lines.append("")
            node_import_lines.extend(f"            {line}" for line in node_imports)
            node_import_lines.append("")

        lines = [
            "# WorkflowSession class",
            "class WorkflowSession:",
            '    """A reusable warm-session wrapper for generated ComfyUI workflows."""',
            "",
            '    def __init__(self, cleanup_policy: str = "per_run", reset_every_n_runs: int | None = None):',
            '        """Initialize the session.',
            "",
            '        Args:',
            '            cleanup_policy: One of "per_run", "session", or "manual".',
            '            reset_every_n_runs: If set, soft-reset every N runs.',
            '        """',
            "        self._bootstrapped = False",
            "        self._custom_nodes_initialized = False",
            "        self._node_instances = {}",
            "        self._lock = threading.Lock()",
            "        self._closed = False",
            "        self._cleanup_policy = cleanup_policy",
            "        self._reset_every_n_runs = reset_every_n_runs",
            "        self._run_count = 0",
            f"        self._queue_size = {plan.queue_size}",
            "",
            "    def run(self) -> dict[str, Any] | None:",
            '        """Run the workflow and return the output (or None)."""',
            "        with self._lock:",
            "            if self._closed:",
            "                raise RuntimeError('Session is closed')",
            "",
            "            if not self._bootstrapped:",
            "                self._bootstrapped = True",
            "                bootstrap_comfyui_runtime()",
            "",
        ]
        lines.extend(
            [
                "            if not self._custom_nodes_initialized:",
                "                self._custom_nodes_initialized = True",
            ]
        )
        if plan.custom_nodes:
            lines.append("                import_custom_nodes()")
        lines.extend(
            [
                "",
                "            prompt = json.loads(json.dumps(build_workflow()))",
                "            extra_pnginfo = build_extra_pnginfo()",
                "",
            ]
        )
        lines.extend(node_import_lines)
        lines.extend(
            [
                "            import torch",
                "            try:",
                "                with torch.inference_mode():",
            ]
        )

        # Add special functions body (inside inference_mode)
        special_body = self.build_function_body(
            plan.special_functions_code, "pass", indentation="                    "
        )
        lines.extend(special_body.splitlines())

        lines.append("                    for q in range(self._queue_size):")

        # Add loop code (node instantiations + calls)
        loop_body = self.build_function_body(
            plan.loop_code, "pass", indentation="                        "
        )
        lines.extend(loop_body.splitlines())

        # Build outputs collection: outputs = {node_id: var_name, ...}
        # Inside try, after for loop (same level as for loop), so 16 spaces
        executed_vars = plan.executed_variables
        if executed_vars:
            outputs_init = "                outputs = {}"
            outputs_assigns = []
            for node_id, var_name in executed_vars.items():
                outputs_assigns.append(f"                outputs[{node_id!r}] = {var_name}")
            run_increment = "                self._run_count += 1"
            outputs_return = "                return outputs"
            lines.append(outputs_init)
            lines.extend(outputs_assigns)
            lines.append(run_increment)
            lines.append(outputs_return)
        else:
            run_increment = "                self._run_count += 1"
            outputs_return = "                return None"
            lines.append(run_increment)
            lines.append(outputs_return)

        lines.extend(
            [
                "            finally:",
                "                if self._cleanup_policy == 'per_run':",
                "                    cleanup_comfyui_runtime(unload_models=True)",
                "",
            ]
        )

        # close() method
        lines.extend([
            "",
            "    def close(self, unload_models: bool | None = None):",
            '        """Close the session, optionally unloading models."""',
            "        with self._lock:",
            "            if self._closed:",
            "                return",
            "            if self._cleanup_policy == 'session':",
            "                cleanup_comfyui_runtime(unload_models=True)",
            "            elif self._cleanup_policy == 'manual':",
            "                self._bootstrapped = False",
            "            self._closed = True",
        ])

        return lines

    def _build_main_wrapper(self, plan: GenerationPlan) -> list[str]:
        return [
            "# Entry point",
            "def main(unload_models: bool | None = None):",
            '    """Backward-compatible entry point using a short-lived WorkflowSession."""',
            '    session = WorkflowSession(cleanup_policy="per_run")',
            "    try:",
            "        session.run()",
            "    finally:",
            "        session.close(unload_models=unload_models)",
        ]

    # ── helpers ──────────────────────────────────────────────────────

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
