import sys
import os

from io import StringIO

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

from comfyui_to_python import ComfyUItoPython

sys.path.append(os.path.dirname(os.path.dirname(ext_dir)))

import server

WEB_DIRECTORY = "js"
NODE_CLASS_MAPPINGS = {}


@server.PromptServer.instance.routes.post("/saveasscript")
async def save_as_script(request):
    try:
        data = await request.json()
        name = data["name"]
        workflow = data["workflow"]

        sio = StringIO()
        ComfyUItoPython(workflow=workflow, output_file=sio)

        sio.seek(0)
        data = sio.read()

        return web.Response(text=data, status=200)
    except Exception as e:
        traceback.print_exc()
        return web.Response(text=str(e), status=500)
