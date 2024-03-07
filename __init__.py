import sys
import os

from io import StringIO
import json

import traceback

from aiohttp import web

ext_dir = os.path.dirname(__file__)
sys.path.append(ext_dir)

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
        name = data['name']
        workflow = data['workflow']
        
        sio = StringIO()
        ComfyUItoPython(workflow=workflow, output_file=sio)
        
        sio.seek(0)
        data = sio.read()
        
        return web.Response(text=data, status=200)
    except Exception as e:
        traceback.print_exc()
        return web.Response(text=str(e), status=500)
