import json
import unittest
from io import StringIO

from comfyui_to_python import ComfyUItoPython


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

        self.assertIn("from nodes import (", generated)
        self.assertIn("LoadImage,", generated)
        self.assertIn("UpscaleModelLoader,", generated)
        self.assertIn("ImageUpscaleWithModel,", generated)
        self.assertIn("NODE_CLASS_MAPPINGS,", generated)
        self.assertIn("loadimage = LoadImage()", generated)
        self.assertIn("upscalemodelloader = UpscaleModelLoader()", generated)
        self.assertIn(
            "imageupscalewithmodel_3 = imageupscalewithmodel.upscale(",
            generated,
        )
        self.assertNotIn('NODE_CLASS_MAPPINGS["UpscaleModelLoader"]()', generated)


if __name__ == "__main__":
    unittest.main()
