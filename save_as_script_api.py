from io import StringIO
from typing import Any, Dict, Mapping

from comfyui_to_python import export_workflow, format_export_exception


def generate_script_response_payload(
    workflow: str,
    *,
    queue_size: int = 1,
    node_class_mappings: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    try:
        buffer = StringIO()
        result = export_workflow(
            workflow=workflow,
            output_file=buffer,
            queue_size=queue_size,
            node_class_mappings=dict(node_class_mappings or {}),
        )
        buffer.seek(0)
        return {
            "ok": True,
            "code": buffer.read(),
            "diagnostics": [
                {
                    "level": diagnostic.level,
                    "message": diagnostic.message,
                    "node_id": diagnostic.node_id,
                    "class_type": diagnostic.class_type,
                    "stage": diagnostic.stage,
                }
                for diagnostic in result.diagnostics
            ],
        }
    except Exception as exc:
        return {
            "ok": False,
            **format_export_exception(exc),
        }
