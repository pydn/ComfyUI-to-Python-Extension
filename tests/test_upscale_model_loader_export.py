import json
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from comfyui_to_python import ComfyUItoPython, run


class UpscaleModelLoader:
    CATEGORY = "loaders"
    FUNCTION = "load_model"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model_name": ("STRING",),
            }
        }

    def load_model(self, model_name):
        return (model_name,)


class LoadImage:
    CATEGORY = "image"
    FUNCTION = "load_image"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("STRING",),
            }
        }

    def load_image(self, image):
        return (image,)


class ImageUpscaleWithModel:
    CATEGORY = "image/upscaling"
    FUNCTION = "upscale"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "upscale_model": ("UPSCALE_MODEL",),
                "image": ("IMAGE",),
            }
        }

    def upscale(self, upscale_model, image):
        return (image,)


class MergeImages:
    CATEGORY = "image"
    FUNCTION = "merge"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "left": ("IMAGE",),
                "right": ("IMAGE",),
            }
        }

    def merge(self, left, right):
        return (left, right)


class HiddenMetadataFilteredNode:
    CATEGORY = "image"
    FUNCTION = "save"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
            },
            "hidden": {
                "prompt": "PROMPT",
                "extra_pnginfo": "EXTRA_PNGINFO",
            },
        }

    def save(self, image):
        return (image,)


class HiddenPromptSeedNode:
    CATEGORY = "sampling"
    FUNCTION = "sample"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "seed": ("INT",),
                "noise_seed": ("INT",),
            },
            "hidden": {
                "prompt": "PROMPT",
            },
        }

    def sample(self, seed, noise_seed, prompt):
        return (seed, noise_seed, prompt)


class UpscaleModelLoaderExportTest(unittest.TestCase):
    def test_top_level_module_preserves_exporter_entrypoints(self):
        from comfyui_to_python import main

        self.assertTrue(callable(ComfyUItoPython))
        self.assertTrue(callable(run))
        self.assertTrue(callable(main))

    def test_export_defers_comfyui_bootstrap_until_main(self):
        workflow = {
            "1": {
                "class_type": "LoadImage",
                "inputs": {
                    "image": "example.png",
                },
            }
        }

        output = StringIO()
        ComfyUItoPython(
            workflow=json.dumps(workflow),
            output_file=output,
            node_class_mappings={
                "LoadImage": LoadImage,
            },
        )

        generated = output.getvalue()

        self.assertIn("def bootstrap_comfyui_runtime()", generated)
        self.assertIn("import comfy.options", generated)
        self.assertIn("comfy.options.enable_args_parsing()", generated)
        self.assertIn("import cuda_malloc", generated)
        self.assertNotIn("\nbootstrap_comfyui_runtime()\n", generated)
        self.assertIn("def main():\n    bootstrap_comfyui_runtime()\n    import torch", generated)
        self.assertLess(generated.index("def bootstrap_comfyui_runtime()"), generated.index("def main():"))
        self.assertLess(generated.index("bootstrap_comfyui_runtime()"), generated.index("import torch"))
        self.assertLess(generated.index("import cuda_malloc"), generated.index("import torch"))

    def test_generated_module_import_does_not_parse_cli_args(self):
        workflow = {
            "1": {
                "class_type": "LoadImage",
                "inputs": {
                    "image": "example.png",
                },
            }
        }

        output = StringIO()
        ComfyUItoPython(
            workflow=json.dumps(workflow),
            output_file=output,
            node_class_mappings={
                "LoadImage": LoadImage,
            },
        )

        generated = output.getvalue()

        self.assertNotIn("\nimport torch\n", generated)

        globals_dict = {"__name__": "generated_workflow_module"}
        with patch.object(sys, "argv", ["generated_workflow.py", "--wrapper-flag"]):
            exec(generated, globals_dict)

        self.assertTrue(callable(globals_dict["main"]))

    def test_upscale_workflow_uses_direct_upscale_model_loader_init(self):
        workflow = {
            "1": {
                "class_type": "LoadImage",
                "inputs": {
                    "image": "example.png",
                },
            },
            "2": {
                "class_type": "UpscaleModelLoader",
                "inputs": {
                    "model_name": "RealESRGAN_x4plus.safetensors",
                },
            },
            "3": {
                "class_type": "ImageUpscaleWithModel",
                "inputs": {
                    "upscale_model": ["2", 0],
                    "image": ["1", 0],
                },
            },
        }

        output = StringIO()
        ComfyUItoPython(
            workflow=json.dumps(workflow),
            output_file=output,
            node_class_mappings={
                "LoadImage": LoadImage,
                "UpscaleModelLoader": UpscaleModelLoader,
                "ImageUpscaleWithModel": ImageUpscaleWithModel,
            },
        )

        generated = output.getvalue()

        self.assertIn("    from nodes import NODE_CLASS_MAPPINGS", generated)
        self.assertIn(f"    from {LoadImage.__module__} import (", generated)
        self.assertIn("LoadImage,", generated)
        self.assertIn("UpscaleModelLoader,", generated)
        self.assertIn("ImageUpscaleWithModel,", generated)
        self.assertIn("loadimage = LoadImage()", generated)
        self.assertIn("upscalemodelloader = UpscaleModelLoader()", generated)
        self.assertIn(
            "imageupscalewithmodel_3 = imageupscalewithmodel.upscale(",
            generated,
        )
        self.assertNotIn('NODE_CLASS_MAPPINGS["UpscaleModelLoader"]()', generated)

    def test_frontend_workflow_metadata_is_embedded_for_reimport(self):
        workflow = {
            "1": {
                "class_type": "LoadImage",
                "inputs": {
                    "image": "example.png",
                },
            }
        }
        frontend_workflow = {
            "version": 0.4,
            "last_node_id": 1,
            "last_link_id": 0,
            "nodes": [],
            "links": [],
            "groups": [],
            "config": {},
            "extra": {},
        }

        output = StringIO()
        ComfyUItoPython(
            workflow=json.dumps(workflow),
            frontend_workflow=json.dumps(frontend_workflow),
            output_file=output,
            node_class_mappings={
                "LoadImage": LoadImage,
            },
        )

        generated = output.getvalue()

        self.assertIn("def build_extra_pnginfo()", generated)
        self.assertIn('"workflow": {', generated)
        self.assertIn('"version": 0.4', generated)
        self.assertIn('"nodes": []', generated)
        self.assertNotIn('"workflow": json.loads(', generated)
        self.assertNotIn('"source": "workflow_api"', generated)

    def test_export_without_frontend_workflow_leaves_png_workflow_metadata_absent(self):
        workflow = {
            "1": {
                "class_type": "LoadImage",
                "inputs": {
                    "image": "example.png",
                },
            }
        }

        output = StringIO()
        ComfyUItoPython(
            workflow=json.dumps(workflow),
            output_file=output,
            node_class_mappings={
                "LoadImage": LoadImage,
            },
        )

        generated = output.getvalue()

        self.assertIn("def build_extra_pnginfo()", generated)
        self.assertIn("return None", generated)
        self.assertNotIn('"workflow": json.loads(', generated)

    def test_export_preserves_unique_variable_names_for_subgraph_node_ids(self):
        workflow = {
            "1:23": {
                "class_type": "LoadImage",
                "inputs": {
                    "image": "left.png",
                },
            },
            "12:3": {
                "class_type": "LoadImage",
                "inputs": {
                    "image": "right.png",
                },
            },
            "20": {
                "class_type": "MergeImages",
                "inputs": {
                    "left": ["1:23", 0],
                    "right": ["12:3", 0],
                },
            },
        }

        output = StringIO()
        ComfyUItoPython(
            workflow=json.dumps(workflow),
            output_file=output,
            node_class_mappings={
                "LoadImage": LoadImage,
                "MergeImages": MergeImages,
            },
        )

        generated = output.getvalue()

        self.assertIn("loadimage_1_23 = loadimage.load_image(", generated)
        self.assertIn("loadimage_12_3 = loadimage.load_image(", generated)
        self.assertIn("mergeimages_20 = mergeimages.merge(", generated)
        self.assertIn("left=get_value_at_index(loadimage_1_23, 0)", generated)
        self.assertIn("right=get_value_at_index(loadimage_12_3, 0)", generated)

    def test_run_cli_export_leaves_png_workflow_metadata_absent(self):
        workflow = {
            "1": {
                "class_type": "LoadImage",
                "inputs": {
                    "image": "example.png",
                },
            }
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            input_file = tmpdir_path / "workflow_api.json"
            output_file = tmpdir_path / "workflow_api.py"

            input_file.write_text(json.dumps(workflow), encoding="utf-8")

            with patch(
                "comfyui_to_python.get_node_class_mappings",
                return_value={"LoadImage": LoadImage},
            ), patch("comfyui_to_python.import_custom_nodes"):
                run(
                    input_file=str(input_file),
                    output_file=str(output_file),
                    queue_size=1,
                )

            generated = output_file.read_text(encoding="utf-8")

        self.assertIn("def build_extra_pnginfo()", generated)
        self.assertIn("return None", generated)
        self.assertNotIn('"workflow": json.loads(', generated)

    def test_export_structures_generated_script_into_readable_sections(self):
        workflow = {
            "1": {
                "class_type": "LoadImage",
                "inputs": {
                    "image": "example.png",
                },
            },
            "2": {
                "class_type": "UpscaleModelLoader",
                "inputs": {
                    "model_name": "RealESRGAN_x4plus.safetensors",
                },
            },
            "3": {
                "class_type": "ImageUpscaleWithModel",
                "inputs": {
                    "upscale_model": ["2", 0],
                    "image": ["1", 0],
                },
            },
        }

        output = StringIO()
        ComfyUItoPython(
            workflow=json.dumps(workflow),
            output_file=output,
            node_class_mappings={
                "LoadImage": LoadImage,
                "UpscaleModelLoader": UpscaleModelLoader,
                "ImageUpscaleWithModel": ImageUpscaleWithModel,
            },
        )

        generated = output.getvalue()

        self.assertIn("# Imports", generated)
        self.assertIn("# Workflow data", generated)
        self.assertIn("# Workflow execution", generated)
        self.assertIn("# Entrypoint", generated)
        self.assertIn("def build_workflow()", generated)
        self.assertIn("def build_extra_pnginfo()", generated)
        self.assertIn("def main()", generated)
        self.assertIn("bootstrap_comfyui_runtime()", generated)
        self.assertNotIn("def initialize_workflow()", generated)
        self.assertNotIn("def run_once(", generated)
        self.assertIn("with torch.inference_mode():", generated)
        self.assertIn("for q in range(1):", generated)
        self.assertIn("workflow = build_workflow()", generated)
        self.assertIn("extra_pnginfo = build_extra_pnginfo()", generated)
        self.assertNotIn('workflow = json.loads("', generated)
        self.assertLess(
            generated.index("def build_workflow()"),
            generated.index("def main()"),
        )

    def test_hidden_metadata_kwargs_follow_function_signature(self):
        workflow = {
            "1": {
                "class_type": "HiddenMetadataFilteredNode",
                "inputs": {
                    "image": "example.png",
                },
            }
        }

        output = StringIO()
        ComfyUItoPython(
            workflow=json.dumps(workflow),
            output_file=output,
            node_class_mappings={
                "HiddenMetadataFilteredNode": HiddenMetadataFilteredNode,
            },
        )

        generated = output.getvalue()

        self.assertIn("hiddenmetadatafilterednode_1 =", generated)
        self.assertNotIn("prompt=prompt", generated)
        self.assertNotIn("extra_pnginfo=extra_pnginfo", generated)

    def test_randomized_seed_inputs_update_prompt_metadata_before_execution(self):
        workflow = {
            "1": {
                "class_type": "HiddenPromptSeedNode",
                "inputs": {
                    "seed": 1,
                    "noise_seed": 2,
                },
            }
        }

        output = StringIO()
        ComfyUItoPython(
            workflow=json.dumps(workflow),
            output_file=output,
            node_class_mappings={
                "HiddenPromptSeedNode": HiddenPromptSeedNode,
            },
        )

        generated = output.getvalue()

        self.assertIn(
            'node_1_seed = prompt["1"]["inputs"]["seed"] = random.randint(1, 2**64)',
            generated,
        )
        self.assertIn(
            'node_1_noise_seed = prompt["1"]["inputs"]["noise_seed"] = random.randint(',
            generated,
        )
        self.assertIn("1, 2**64", generated)
        self.assertIn("seed=node_1_seed", generated)
        self.assertIn("noise_seed=node_1_noise_seed", generated)
        self.assertIn("prompt=prompt", generated)


if __name__ == "__main__":
    unittest.main()
