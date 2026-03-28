import json
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


class UpscaleModelLoaderExportTest(unittest.TestCase):
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

        self.assertIn("from nodes import NODE_CLASS_MAPPINGS", generated)
        self.assertIn(f"from {LoadImage.__module__} import (", generated)
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

        self.assertIn('extra_pnginfo = {', generated)
        self.assertIn('"workflow": json.loads(', generated)
        self.assertIn('"version": 0.4', generated)
        self.assertIn('"nodes": []', generated)
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

        self.assertIn("extra_pnginfo = None", generated)
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

    def test_run_accepts_frontend_workflow_file_for_cli_metadata(self):
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
            "nodes": [
                {
                    "id": 1,
                    "type": "LoadImage",
                    "pos": [0, 0],
                    "size": [210, 60],
                    "flags": {},
                    "order": 0,
                    "mode": 0,
                    "inputs": [],
                    "outputs": [],
                    "properties": {},
                    "widgets_values": ["example.png"],
                }
            ],
            "links": [],
            "groups": [],
            "config": {},
            "extra": {},
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            input_file = tmpdir_path / "workflow_api.json"
            frontend_file = tmpdir_path / "workflow.json"
            output_file = tmpdir_path / "workflow_api.py"

            input_file.write_text(json.dumps(workflow), encoding="utf-8")
            frontend_file.write_text(json.dumps(frontend_workflow), encoding="utf-8")

            with patch(
                "comfyui_to_python.get_node_class_mappings",
                return_value={"LoadImage": LoadImage},
            ), patch("comfyui_to_python.import_custom_nodes"):
                run(
                    input_file=str(input_file),
                    frontend_workflow_file=str(frontend_file),
                    output_file=str(output_file),
                    queue_size=1,
                )

            generated = output_file.read_text(encoding="utf-8")

        self.assertIn('"version": 0.4', generated)
        self.assertIn('"type": "LoadImage"', generated)


if __name__ == "__main__":
    unittest.main()
