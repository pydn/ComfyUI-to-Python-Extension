import json
import unittest
from io import StringIO
from pathlib import Path

from comfyui_to_python import ComfyUItoPython


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "unit" / "generator_codegen"


class AnySwitchRgthree:
    CATEGORY = "utils"
    FUNCTION = "switch"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL",),
            }
        }

    def switch(self, model):
        return (model,)


class DualClipLoader:
    CATEGORY = "loaders"
    FUNCTION = "load_clip"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "clip_name": ("STRING",),
            }
        }

    def load_clip(self, clip_name):
        return (clip_name,)


class PowerLoraLoaderRgthree:
    CATEGORY = "loaders"
    FUNCTION = "load_loras"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "PowerLoraLoaderHeaderWidget": ("DICT",),
                "model": ("MODEL",),
                "clip": ("CLIP",),
            }
        }

    def load_loras(self, **kwargs):
        return (kwargs,)


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


class VaeDecode:
    CATEGORY = "latent"
    FUNCTION = "decode"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "samples": ("LATENT",),
            }
        }

    def decode(self, samples):
        return (samples,)


class WindowsPathNode:
    CATEGORY = "paths"
    FUNCTION = "open_path"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "path": ("STRING",),
            }
        }

    def open_path(self, path):
        return (path,)


class TextConcatenateNode:
    CATEGORY = "text"
    FUNCTION = "text_concatenate"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "delimiter": ("STRING",),
                "clean_whitespace": ("STRING",),
                "text_b": ("STRING",),
            }
        }

    def text_concatenate(self, delimiter, clean_whitespace, text_b):
        return (delimiter, clean_whitespace, text_b)


class StringSeedNode:
    CATEGORY = "sampling"
    FUNCTION = "sample"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "seed": ("STRING",),
            },
            "hidden": {
                "prompt": "PROMPT",
            },
        }

    def sample(self, seed, prompt):
        return (seed, prompt)


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def export_workflow(workflow: dict, node_class_mappings: dict) -> str:
    output = StringIO()
    ComfyUItoPython(
        workflow=json.dumps(workflow),
        output_file=output,
        node_class_mappings=node_class_mappings,
    )
    return output.getvalue()


class GeneratorCodegenIssueRegressionTest(unittest.TestCase):
    def test_export_uses_dictionary_expansion_for_rgthree_symbol_heavy_input_names(self):
        generated = export_workflow(
            load_fixture("unsafe-rgthree-kwargs.json"),
            {
                "AnySwitchRgthree": AnySwitchRgthree,
                "DualClipLoader": DualClipLoader,
                "PowerLoraLoaderRgthree": PowerLoraLoaderRgthree,
            },
        )

        self.assertIn(
            'powerloraloaderrgthree_631 = powerloraloaderrgthree.load_loras(',
            generated,
        )
        self.assertIn(
            'PowerLoraLoaderHeaderWidget={"type": "PowerLoraLoaderHeaderWidget"}',
            generated,
        )
        self.assertIn('**{"\\u2795 Add Lora": ""}', generated)
        self.assertNotIn('➕ Add Lora=""', generated)

    def test_export_sanitizes_subgraph_identifiers_for_upscaler_workflows(self):
        generated = export_workflow(
            load_fixture("subgraph-upscaler-identifiers.json"),
            {
                "VaeDecode": VaeDecode,
                "UpscaleModelLoader": UpscaleModelLoader,
                "ImageUpscaleWithModel": ImageUpscaleWithModel,
            },
        )

        self.assertIn("upscalemodelloader_42_0 = upscalemodelloader.load_model(", generated)
        self.assertIn(
            "imageupscalewithmodel_42_1 = imageupscalewithmodel.upscale(",
            generated,
        )
        self.assertIn(
            "upscale_model=get_value_at_index(upscalemodelloader_42_0, 0)",
            generated,
        )
        self.assertNotIn("imageupscalewithmodel_42:1", generated)
        self.assertNotIn("upscalemodelloader_42:0", generated)

    def test_export_preserves_windows_style_model_paths(self):
        generated = export_workflow(
            load_fixture("windows-path-string.json"),
            {
                "WindowsPathNode": WindowsPathNode,
            },
        )

        globals_dict = {"__name__": "generated_workflow_module"}
        exec(generated, globals_dict)

        self.assertEqual(
            globals_dict["build_workflow"]()["1"]["inputs"]["path"],
            r"C:\ComfyUI\models\upscale_models\RealESRGAN_x4plus.safetensors",
        )

    def test_export_preserves_trailing_backslash_string_literals(self):
        generated = export_workflow(
            load_fixture("trailing-backslash-string.json"),
            {
                "TextConcatenateNode": TextConcatenateNode,
            },
        )

        globals_dict = {"__name__": "generated_workflow_module"}
        exec(generated, globals_dict)

        self.assertEqual(
            globals_dict["build_workflow"]()["1"]["inputs"]["text_b"],
            "\\",
        )

    def test_export_randomizes_string_seed_inputs_as_strings(self):
        generated = export_workflow(
            load_fixture("string-seed-node.json"),
            {
                "StringSeedNode": StringSeedNode,
            },
        )

        self.assertIn(
            'node_1_seed = prompt["1"]["inputs"]["seed"] = str(random.randint(1, 2**64))',
            generated,
        )
        self.assertIn("seed=node_1_seed", generated)

    def test_issue_cluster_regressions_render_parseable_python(self):
        workflows = [
            (
                    load_fixture("unsafe-rgthree-kwargs.json"),
                    {
                        "AnySwitchRgthree": AnySwitchRgthree,
                        "DualClipLoader": DualClipLoader,
                        "PowerLoraLoaderRgthree": PowerLoraLoaderRgthree,
                    },
                ),
            (
                load_fixture("subgraph-upscaler-identifiers.json"),
                {
                    "VaeDecode": VaeDecode,
                    "UpscaleModelLoader": UpscaleModelLoader,
                    "ImageUpscaleWithModel": ImageUpscaleWithModel,
                },
            ),
            (
                load_fixture("trailing-backslash-string.json"),
                {
                    "TextConcatenateNode": TextConcatenateNode,
                },
            ),
            (
                load_fixture("windows-path-string.json"),
                {
                    "WindowsPathNode": WindowsPathNode,
                },
            ),
            (
                load_fixture("string-seed-node.json"),
                {
                    "StringSeedNode": StringSeedNode,
                },
            ),
        ]

        for workflow, mapping in workflows:
            generated = export_workflow(workflow, mapping)
            compile(generated, "<generated_workflow>", "exec")


if __name__ == "__main__":
    unittest.main()
