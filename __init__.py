import sys
import os
import traceback

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

from save_as_script_api import generate_script_response_payload

sys.path.append(os.path.dirname(os.path.dirname(ext_dir)))

import server

WEB_DIRECTORY = "js"
NODE_CLASS_MAPPINGS = {}


@server.PromptServer.instance.routes.post("/saveasscript")
async def save_as_script(request):
    try:
        data = await request.json()
        workflow = data["workflow"]
        payload = generate_script_response_payload(workflow)
        if payload["ok"]:
            return web.Response(text=payload["code"], status=200)
        return web.json_response(payload, status=400)
    except Exception as e:
        traceback.print_exc()
        return web.json_response(
            {
                "ok": False,
                "error": str(e),
                "stage": "unexpected",
            },
            status=500,
        )
