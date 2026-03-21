import sys
import os
import traceback
from io import StringIO

from aiohttp import web

ext_dir = os.path.dirname(__file__)
sys.path.append(ext_dir)

try:
    import black
except ImportError:
    print("Unable to import requirements for ComfyUI-SaveAsScript.")
    print("Installing...")

    import importlib

    spec = importlib.util.spec_from_file_location(
        "impact_install", os.path.join(os.path.dirname(__file__), "install.py")
    )
    impact_install = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(impact_install)

    print("Successfully installed. Hopefully, at least.")

# Prevent reimporting of custom nodes
os.environ["RUNNING_IN_COMFYUI"] = "TRUE"

from comfyui_to_python import export_workflow, format_export_exception

sys.path.append(os.path.dirname(os.path.dirname(ext_dir)))

import server

WEB_DIRECTORY = "js"
NODE_CLASS_MAPPINGS = {}


@server.PromptServer.instance.routes.post("/saveasscript")
async def save_as_script(request):
    try:
        data = await request.json()
        workflow = data["workflow"]
        output = StringIO()
        result = export_workflow(workflow=workflow, output_file=output)
        return web.Response(text=result.code, status=200)
    except Exception as exc:
        traceback.print_exc()
        payload = format_export_exception(exc)
        status = 400 if payload.get("stage") != "unexpected" else 500
        return web.json_response(payload, status=status)
