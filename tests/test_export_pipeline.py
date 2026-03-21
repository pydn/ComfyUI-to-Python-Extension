import ast
import json
import tempfile
import unittest
from pathlib import Path

try:
    import black
except ImportError:
    black = None

from comfyui_to_python import (
    ExportStageError,
    IdentifierService,
    WorkflowNormalizer,
    export_workflow,
)
from comfyui_to_python_utils import normalize_path
from save_as_script_api import generate_script_response_payload


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


class SubgraphBridge:
    CATEGORY = "utility"
    FUNCTION = "bridge"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"source": ("ANY",)}}

    def bridge(self, source):
        return (source,)


class UpscaleModelLoader:
    CATEGORY = "loaders"
    FUNCTION = "load_model"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"model_name": ("STRING",)}}

    def load_model(self, model_name):
        return (f"upscale:{model_name}",)


class ImageUpscaler:
    CATEGORY = "image/upscale"
    FUNCTION = "upscale"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"upscale_model": ("MODEL",), "image": ("IMAGE",)}}

    def upscale(self, upscale_model, image):
        return (f"{upscale_model}:{image}",)


NODE_CLASS_MAPPINGS = {
    "CheckpointLoaderSimple": CheckpointLoaderSimple,
    "CLIPTextEncode": CLIPTextEncode,
    "KSampler": KSampler,
    "SubgraphBridge": SubgraphBridge,
    "UpscaleModelLoader": UpscaleModelLoader,
    "ImageUpscaler": ImageUpscaler,
}


def read_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


class ExportPipelineTests(unittest.TestCase):
    def test_identifier_service_generates_safe_unique_names(self):
        identifiers = IdentifierService()
        self.assertEqual(identifiers.allocate("class", prefix="node"), "class_node")
        self.assertEqual(identifiers.allocate("class", prefix="node"), "class_node_2")
        self.assertEqual(identifiers.allocate("123 loader", prefix="node"), "node_123_loader")
        self.assertEqual(identifiers.allocate("➕", prefix="node"), "node")

    def test_workflow_normalizer_supports_subgraph_references(self):
        normalized = WorkflowNormalizer().normalize(json.loads(read_fixture("subgraph_workflow.json")))
        self.assertEqual(normalized["2"].inputs["source"].node_id, "1")
        self.assertEqual(normalized["3"].inputs["model"].output_index, 0)

    def test_export_workflow_produces_valid_python_for_basic_fixture(self):
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
            if black is not None:
                black.format_str(code, mode=black.Mode())
            self.assertIn("checkpointloadersimple_1", code)
            self.assertIn("for q in range(2)", code)

    def test_export_workflow_handles_symbol_heavy_node_metadata(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "workflow.py"
            export_workflow(
                workflow=read_fixture("symbol_name_workflow.json"),
                output_file=str(output_path),
                node_class_mappings=NODE_CLASS_MAPPINGS,
            )

            code = output_path.read_text(encoding="utf-8")
            ast.parse(code)
            self.assertNotIn("🚀", code)
            self.assertIn("ksampler_3", code)

    def test_export_workflow_supports_custom_upscale_fixture(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "workflow.py"
            export_workflow(
                workflow=read_fixture("custom_upscale_workflow.json"),
                output_file=str(output_path),
                node_class_mappings=NODE_CLASS_MAPPINGS,
            )

            code = output_path.read_text(encoding="utf-8")
            ast.parse(code)
            self.assertIn('NODE_CLASS_MAPPINGS["UpscaleModelLoader"]()', code)
            self.assertIn("imageupscaler_2", code)

    def test_missing_custom_node_returns_structured_error(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "workflow.py"
            with self.assertRaises(ExportStageError) as exc_info:
                export_workflow(
                    workflow=read_fixture("custom_upscale_workflow.json"),
                    output_file=str(output_path),
                    node_class_mappings={"ImageUpscaler": ImageUpscaler},
                )

        payload = exc_info.exception.to_payload()
        self.assertEqual(payload["stage"], "resolve-node")
        self.assertEqual(payload["class_type"], "UpscaleModelLoader")

    def test_save_as_script_payload_reports_success(self):
        payload = generate_script_response_payload(
            read_fixture("basic_workflow.json"),
            queue_size=3,
            node_class_mappings=NODE_CLASS_MAPPINGS,
        )
        self.assertTrue(payload["ok"])
        ast.parse(payload["code"])
        self.assertEqual(payload["diagnostics"][0]["level"], "warning")

    def test_save_as_script_payload_reports_error_with_context(self):
        payload = generate_script_response_payload(
            '{"1": {"class_type": "MissingNode", "inputs": {}}}'
        )
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["stage"], "resolve-node")
        self.assertEqual(payload["class_type"], "MissingNode")

    def test_normalize_path_handles_windows_style_paths(self):
        self.assertEqual(normalize_path("foo\\bar\\baz"), str(Path("foo") / "bar" / "baz"))


if __name__ == "__main__":
    unittest.main()
