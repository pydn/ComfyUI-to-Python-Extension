# Imports
import json
import os
import random
import sys
from typing import Sequence, Mapping, Any, Union


def get_value_at_index(obj: Union[Sequence, Mapping], index: int) -> Any:
    """Return a sequence or mapping result item by index."""
    try:
        return obj[index]
    except KeyError:
        return obj["result"][index]


def get_comfyui_path() -> str:
    """Return the configured ComfyUI path, preferring COMFYUI_PATH when set."""
    comfyui_path = os.environ.get("COMFYUI_PATH")
    if comfyui_path:
        return comfyui_path
    return find_path("ComfyUI")


def find_path(name: str, path: str = None) -> str:
    """Recursively search parent folders until the named entry is found."""
    if path is None:
        path = os.getcwd()

    if name in os.listdir(path):
        path_name = os.path.join(path, name)
        print(f"{name} found: {path_name}")
        return path_name

    parent_directory = os.path.dirname(path)
    if parent_directory == path:
        return None

    return find_path(name, parent_directory)


def add_comfyui_directory_to_sys_path() -> None:
    """Add the ComfyUI checkout to sys.path."""
    comfyui_path = get_comfyui_path()
    if comfyui_path is not None and os.path.isdir(comfyui_path):
        if comfyui_path in sys.path:
            sys.path.remove(comfyui_path)
        sys.path.insert(0, comfyui_path)
        print(f"'{comfyui_path}' added to sys.path")


def add_extra_model_paths() -> None:
    """Load ComfyUI extra model paths configuration when available."""
    try:
        from main import load_extra_path_config
    except ImportError:
        print(
            "Could not import load_extra_path_config from main.py. Looking in utils.extra_config instead."
        )
        from utils.extra_config import load_extra_path_config

    extra_model_paths = find_path("extra_model_paths.yaml")
    if extra_model_paths is not None:
        load_extra_path_config(extra_model_paths)
    else:
        print("Could not find the extra_model_paths config file.")


def bootstrap_comfyui_runtime() -> None:
    """Mirror the allocator-related ComfyUI startup steps before torch import."""
    add_comfyui_directory_to_sys_path()

    import comfy.options

    comfy.options.enable_args_parsing()

    from comfy.cli_args import args

    if os.name == "nt":
        os.environ["MIMALLOC_PURGE_DELAY"] = "0"

    if args.default_device is not None:
        default_dev = args.default_device
        devices = list(range(32))
        devices.remove(default_dev)
        devices.insert(0, default_dev)
        devices = ",".join(map(str, devices))
        os.environ["CUDA_VISIBLE_DEVICES"] = str(devices)
        os.environ["HIP_VISIBLE_DEVICES"] = str(devices)

    if args.cuda_device is not None:
        os.environ["CUDA_VISIBLE_DEVICES"] = str(args.cuda_device)
        os.environ["HIP_VISIBLE_DEVICES"] = str(args.cuda_device)
        os.environ["ASCEND_RT_VISIBLE_DEVICES"] = str(args.cuda_device)

    if args.oneapi_device_selector is not None:
        os.environ["ONEAPI_DEVICE_SELECTOR"] = args.oneapi_device_selector

    if args.deterministic and "CUBLAS_WORKSPACE_CONFIG" not in os.environ:
        os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"

    import cuda_malloc

    if "rocm" in cuda_malloc.get_torch_version_noimport():
        os.environ["OCL_SET_SVM_SIZE"] = "262144"


# Runtime support

bootstrap_comfyui_runtime()
import torch

add_extra_model_paths()


# Workflow data
def build_workflow() -> dict[str, Any]:
    return {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "v1-5-pruned-emaonly-fp16.safetensors"},
        },
        "2": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "text": "a small cottage in a meadow, soft daylight",
                "clip": ["1", 1],
            },
        },
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "blurry, low quality", "clip": ["1", 1]},
        },
        "4": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 512, "height": 512, "batch_size": 1},
        },
        "5": {
            "class_type": "KSampler",
            "inputs": {
                "seed": 1,
                "steps": 4,
                "cfg": 7,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": 1,
                "model": ["1", 0],
                "positive": ["2", 0],
                "negative": ["3", 0],
                "latent_image": ["4", 0],
            },
        },
        "6": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["5", 0], "vae": ["1", 2]},
        },
        "7": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": "E2E_text_to_image", "images": ["6", 0]},
        },
    }


def build_extra_pnginfo() -> dict[str, Any] | None:
    return None


workflow = build_workflow()
prompt = json.loads(json.dumps(workflow))
extra_pnginfo = build_extra_pnginfo()

# Workflow execution
# Node imports
from nodes import (
    CLIPTextEncode,
    CheckpointLoaderSimple,
    EmptyLatentImage,
    KSampler,
    NODE_CLASS_MAPPINGS,
    SaveImage,
    VAEDecode,
)


def main():
    with torch.inference_mode():
        checkpointloadersimple = CheckpointLoaderSimple()
        checkpointloadersimple_1 = checkpointloadersimple.load_checkpoint(
            ckpt_name="v1-5-pruned-emaonly-fp16.safetensors"
        )
        cliptextencode = CLIPTextEncode()
        cliptextencode_2 = cliptextencode.encode(
            text="a small cottage in a meadow, soft daylight",
            clip=get_value_at_index(checkpointloadersimple_1, 1),
        )
        cliptextencode_3 = cliptextencode.encode(
            text="blurry, low quality",
            clip=get_value_at_index(checkpointloadersimple_1, 1),
        )
        emptylatentimage = EmptyLatentImage()
        emptylatentimage_4 = emptylatentimage.generate(
            width=512, height=512, batch_size=1
        )
        ksampler = KSampler()
        vaedecode = VAEDecode()
        saveimage = SaveImage()
        for q in range(1):
            node_5_seed = prompt["5"]["inputs"]["seed"] = random.randint(1, 2**64)
            ksampler_5 = ksampler.sample(
                seed=node_5_seed,
                steps=4,
                cfg=7,
                sampler_name="euler",
                scheduler="normal",
                denoise=1,
                model=get_value_at_index(checkpointloadersimple_1, 0),
                positive=get_value_at_index(cliptextencode_2, 0),
                negative=get_value_at_index(cliptextencode_3, 0),
                latent_image=get_value_at_index(emptylatentimage_4, 0),
            )
            vaedecode_6 = vaedecode.decode(
                samples=get_value_at_index(ksampler_5, 0),
                vae=get_value_at_index(checkpointloadersimple_1, 2),
            )
            saveimage_7 = saveimage.save_images(
                filename_prefix="E2E_text_to_image",
                images=get_value_at_index(vaedecode_6, 0),
                prompt=prompt,
                extra_pnginfo=extra_pnginfo,
            )


# Entrypoint
if __name__ == "__main__":
    main()
