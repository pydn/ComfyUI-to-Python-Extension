import ast
import json
import tempfile
import unittest
from pathlib import Path

from comfyui_to_python import ExportStageError, export_workflow, format_export_exception


FIXTURES_DIR = Path(__file__).parent / "fixtures"


class CheckpointLoaderSimple:
    CATEGORY = "loaders"
    FUNCTION = "load_checkpoint"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"ckpt_name": ("STRING",)}}

    def load_checkpoint(self, ckpt_name):
        return (f"model:{ckpt_name}", f"clip:{ckpt_name}", f"vae:{ckpt_name}")


class CLIPTextEncode:
    CATEGORY = "conditioning"
    FUNCTION = "encode"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"text": ("STRING",), "clip": ("CLIP",)}}

    def encode(self, text, clip):
        return (f"{text}:{clip}",)


class KSampler:
    CATEGORY = "sampling"
    FUNCTION = "sample"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"seed": ("INT",), "model": ("MODEL",), "positive": ("COND",)}}

    def sample(self, seed, model, positive, **kwargs):
        return (f"{seed}:{model}:{positive}:{kwargs}",)


class FancyCustomSampler:
    CATEGORY = "custom/sampling"
    FUNCTION = "sample"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"seed": ("INT",)}}

    def sample(self, seed, **kwargs):
        return (f"{seed}:{kwargs}",)


NODE_CLASS_MAPPINGS = {
    "CheckpointLoaderSimple": CheckpointLoaderSimple,
    "CLIPTextEncode": CLIPTextEncode,
    "KSampler": KSampler,
    "Power Lora Loader (rgthree)": FancyCustomSampler,
}


def read_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


class ExportPipelineTests(unittest.TestCase):
    def test_export_workflow_generates_valid_python_for_basic_fixture(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "workflow.py"
            result = export_workflow(
                input_file=str(FIXTURES_DIR / "basic_workflow.json"),
                output_file=str(output_path),
                queue_size=2,
                node_class_mappings=NODE_CLASS_MAPPINGS,
            )

            code = output_path.read_text(encoding="utf-8")
            self.assertEqual(result.code, code)
            ast.parse(code)
            self.assertIn("from nodes import NODE_CLASS_MAPPINGS", code)
            self.assertIn("for q in range(2)", code)
            self.assertIn("ksampler_3", code)

    def test_export_workflow_uses_safe_custom_node_lookup_and_dict_unpack(self):
        workflow = json.dumps(
            {
                "1": {
                    "class_type": "Power Lora Loader (rgthree)",
                    "inputs": {
                        "seed": 1,
                        "➕ Add Lora": "foo.safetensors",
                        "in": "reserved",
                    },
                }
            }
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "workflow.py"
            export_workflow(
                workflow=workflow,
                output_file=str(output_path),
                node_class_mappings=NODE_CLASS_MAPPINGS,
            )

            code = output_path.read_text(encoding="utf-8")
            ast.parse(code)
            self.assertIn('NODE_CLASS_MAPPINGS["Power Lora Loader (rgthree)"]()', code)
            self.assertNotIn("from nodes import NODE_CLASS_MAPPINGS, Power Lora Loader", code)
            self.assertIn('**{"\\u2795 Add Lora": "foo.safetensors"}', code)
            self.assertIn('**{"in": "reserved"}', code)

    def test_missing_custom_node_returns_structured_error_payload(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "workflow.py"
            with self.assertRaises(ExportStageError) as exc_info:
                export_workflow(
                    workflow=read_fixture("basic_workflow.json"),
                    output_file=str(output_path),
                    node_class_mappings={"KSampler": KSampler},
                )

        payload = format_export_exception(exc_info.exception)
        self.assertEqual(payload["stage"], "resolve-node")
        self.assertEqual(payload["class_type"], "CheckpointLoaderSimple")


if __name__ == "__main__":
    unittest.main()
