# Imports
import importlib.util
import json
import logging
import os
import random
import sys
from typing import Sequence, Mapping, Any, Union

log = logging.getLogger(__name__)


def _load_module(module_name: str, filepath: str) -> Any:
    """Load a Python module from an explicit file path, bypassing sys.path.

    This eliminates ALL bare import shadowing attacks by loading modules
    from verified file paths instead of relying on sys.path resolution.
    """
    if not os.path.isfile(filepath):
        log.debug("Module file not found: %s (%s)", module_name, filepath)
        return None
    try:
        spec = importlib.util.spec_from_file_location(module_name, filepath)
        if spec is None or spec.loader is None:
            log.debug("Could not create spec for %s at %s", module_name, filepath)
            return None
        mod = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = mod
        spec.loader.exec_module(mod)
        return mod
    except Exception as e:
        log.debug("Failed to load %s from %s: %s", module_name, filepath, e)
        return None


def _load_module_temp(module_name: str, filepath: str) -> Any:
    """Load a module via _load_module() then remove it from sys.modules.

    Used during bootstrap for modules that ComfyUI's import chain also loads
    normally — prevents the cached copy from conflicting with later imports.
    """
    mod = _load_module(module_name, filepath)
    sys.modules.pop(module_name, None)
    return mod


def _is_comfyui_directory(path: str) -> bool:
    """Verify a directory has ComfyUI structural markers (nodes.py)."""
    if not os.path.isdir(path):
        return False
    return os.path.isfile(os.path.join(path, "nodes.py"))


def _find_from_extension_location() -> str | None:
    """Walk up from this file's location to find ComfyUI root."""
    ext_dir = os.path.dirname(os.path.realpath(__file__))
    candidate = ext_dir
    for _ in range(10):
        parent = os.path.dirname(candidate)
        if parent == candidate:
            break
        candidate = parent
        if os.path.basename(candidate) == "ComfyUI":
            if _is_comfyui_directory(candidate):
                return candidate
    return None


def get_value_at_index(obj: Union[Sequence, Mapping], index: int) -> Any:
    """Return a sequence or mapping result item by index."""
    try:
        return obj[index]
    except KeyError:
        return obj["result"][index]


def get_comfyui_path() -> str | None:
    """Resolve ComfyUI path via prioritized multi-strategy fallback.

    Strategy order:
      1. COMFYUI_PATH env var (verified with _is_comfyui_directory)
      2. Relative walk from extension location (realpath + verified)
      3. CWD walk (legacy fallback, depth-limited)
    """
    p = os.environ.get("COMFYUI_PATH")
    if p and _is_comfyui_directory(p):
        return p
    p = _find_from_extension_location()
    if p:
        return p
    return find_path("ComfyUI", max_depth=20)


def find_path(name: str, max_depth: int = 20) -> str | None:
    """Iteratively walk up from CWD to find a directory by name.

    Depth-limited to prevent slow startup on deep trees.
    Each candidate verified by _is_comfyui_directory() at the caller.
    """
    candidate = os.getcwd()
    for _ in range(max_depth):
        parent = os.path.dirname(candidate)
        if parent == candidate:
            break
        candidate = parent
        if os.path.basename(candidate) == name:
            return candidate
    return None


def add_comfyui_directory_to_sys_path() -> None:
    """Add the ComfyUI checkout to sys.path (idempotent — insert-once, no gap)."""
    comfyui_path = get_comfyui_path()
    if comfyui_path is not None and os.path.isdir(comfyui_path):
        if comfyui_path not in sys.path:
            sys.path.insert(0, comfyui_path)
            log.debug("Added %s to sys.path", comfyui_path)


def add_extra_model_paths() -> None:
    """Load ComfyUI extra model paths configuration when available."""
    comfyui_path = get_comfyui_path()
    if comfyui_path is None:
        log.debug("Cannot load extra model paths: ComfyUI path not found")
        return

    # Try main.py first, then utils/extra_config.py — both via _load_module()
    main_mod = _load_module("comfy_main", os.path.join(comfyui_path, "main.py"))
    if main_mod is not None and hasattr(main_mod, "load_extra_path_config"):
        load_extra_path_config = getattr(main_mod, "load_extra_path_config")
    else:
        log.debug("main.py not available, trying utils/extra_config.py")
        extra_config_mod = _load_module(
            "extra_config", os.path.join(comfyui_path, "utils", "extra_config.py")
        )
        if extra_config_mod is None or not hasattr(
            extra_config_mod, "load_extra_path_config"
        ):
            log.debug("Could not find load_extra_path_config in either path")
            return
        load_extra_path_config = getattr(extra_config_mod, "load_extra_path_config")

    extra_model_paths = find_path("extra_model_paths.yaml")
    if extra_model_paths is not None:
        load_extra_path_config(extra_model_paths)
    else:
        log.debug("Could not find the extra_model_paths config file.")


def bootstrap_comfyui_runtime() -> None:
    """Mirror the allocator-related ComfyUI startup steps before torch import."""
    add_comfyui_directory_to_sys_path()
    comfyui_path = get_comfyui_path()
    if comfyui_path is None:
        log.debug("bootstrap_comfyui_runtime: ComfyUI path not found")
        return

    # Use _load_module for file-based isolation, but with temporary names so
    # the modules are removed from sys.modules after reading values.
    # This prevents conflicts when ComfyUI's internal import chain (e.g.
    # nodes.py -> comfy.cli_args) later loads these modules normally.
    options_mod = _load_module_temp(
        "_bootstrap_options", os.path.join(comfyui_path, "comfy", "options.py")
    )
    if options_mod is not None:
        options_mod.enable_args_parsing()

    cli_args_mod = _load_module_temp(
        "_bootstrap_cli_args", os.path.join(comfyui_path, "comfy", "cli_args.py")
    )
    args = getattr(cli_args_mod, "args", None) if cli_args_mod else None

    if args is None:
        return

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

    cuda_malloc_mod = _load_module_temp(
        "_bootstrap_cuda_malloc", os.path.join(comfyui_path, "cuda_malloc.py")
    )
    if (
        cuda_malloc_mod is not None
        and hasattr(cuda_malloc_mod, "get_torch_version_noimport")
        and "rocm" in cuda_malloc_mod.get_torch_version_noimport()
    ):
        os.environ["OCL_SET_SVM_SIZE"] = "262144"


def cleanup_comfyui_runtime(unload_models: bool | None = None) -> None:
    """Best-effort cleanup for embedded or repeated generated-script execution."""
    import gc

    def run_cleanup_hook(name: str, should_run: bool = True) -> None:
        if not should_run or not hasattr(model_management, name):
            return
        cleanup_fn = getattr(model_management, name)
        try:
            cleanup_fn()
        except Exception as exc:
            warnings.warn(
                f"ComfyUI cleanup hook {name} failed during teardown: {exc}",
                RuntimeWarning,
                stacklevel=2,
            )

    should_unload = unload_models
    if should_unload is None:
        should_unload = os.environ.get(
            "COMFYUI_TOPYTHON_UNLOAD_MODELS", ""
        ).lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    try:
        import comfy.model_management as model_management
    except ModuleNotFoundError:
        gc.collect()
        return

    run_cleanup_hook("cleanup_models_gc")
    run_cleanup_hook("unload_all_models", should_run=should_unload)
    run_cleanup_hook("soft_empty_cache")
    gc.collect()


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
def main(unload_models: bool | None = None):
    bootstrap_comfyui_runtime()
    add_extra_model_paths()

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

    import torch

    try:
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
    finally:
        cleanup_comfyui_runtime(unload_models=unload_models)


# Entrypoint
if __name__ == "__main__":
    main()
