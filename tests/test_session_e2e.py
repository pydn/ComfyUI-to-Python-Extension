"""End-to-end tests for session execution mode feature.

Covers:
- Code generation correctness (session vs oneshot)
- Runtime execution of generated scripts
- Multi-run session behavior
"""

import ast
import json
import os
import subprocess
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMFYUI_PATH = os.environ.get("COMFYUI_PATH", str(ROOT.parent / "ComfyUI"))

# Minimal mock nodes for export
class KSamplerMock:
    CATEGORY = "sampling"
    FUNCTION = "sample"
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "seed": ("INT", {"default": 0}),
                "steps": ("INT", {"default": 20}),
                "cfg": ("FLOAT", {"default": 8.0}),
                "sampler_name": (["euler", "heun"],),
                "scheduler": (["normal"],),
                "denoise": ("FLOAT", {"default": 1.0}),
                "model": ("MODEL",),
                "positive": ("CONDITIONING",),
                "negative": ("CONDITIONING",),
                "latent_image": ("LATENT",),
            }
        }
    def sample(self, seed, steps, cfg, sampler_name, scheduler, denoise, model, positive, negative, latent_image):
        return ({"samples": latent_image},)

class CheckpointLoaderMock:
    CATEGORY = "loaders"
    FUNCTION = "load_checkpoint"
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "ckpt_name": ("STRING",),
            }
        }
    def load_checkpoint(self, ckpt_name):
        return (None, None, None)

class VAEDecodeMock:
    CATEGORY = "latent"
    FUNCTION = "decode"
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "samples": ("LATENT",),
                "vae": ("VAE",),
            }
        }
    def decode(self, samples, vae):
        return (samples,)

class CLIPTextEncodeMock:
    CATEGORY = "conditioning"
    FUNCTION = "encode"
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING",),
                "clip": ("CLIP",),
            }
        }
    def encode(self, text, clip):
        return ([],)

class EmptyLatentImageMock:
    CATEGORY = "latent"
    FUNCTION = "generate"
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "width": ("INT", {"default": 512}),
                "height": ("INT", {"default": 512}),
                "batch_size": ("INT", {"default": 1}),
            }
        }
    def generate(self, width, height, batch_size):
        return ({"samples": {}},)

class SaveImageMock:
    CATEGORY = "image"
    FUNCTION = "save"
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "filename_prefix": ("STRING",),
            }
        }
    def save(self, images, filename_prefix):
        return ()

NODENAMES = {
    "CheckpointLoaderSimple": CheckpointLoaderMock,
    "CLIPTextEncode": CLIPTextEncodeMock,
    "KSampler": KSamplerMock,
    "VAEDecode": VAEDecodeMock,
    "EmptyLatentImage": EmptyLatentImageMock,
    "SaveImage": SaveImageMock,
}

TEXT_TO_IMAGE_WORKFLOW = {
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
        "inputs": {
            "text": "blurry, low quality",
            "clip": ["1", 1],
        },
    },
    "4": {
        "class_type": "EmptyLatentImage",
        "inputs": {"width": 512, "height": 512, "batch_size": 1},
    },
    "5": {
        "class_type": "KSampler",
        "inputs": {
            "seed": 1, "steps": 4, "cfg": 7, "sampler_name": "euler",
            "scheduler": "normal", "denoise": 1,
            "model": ["1", 0], "positive": ["2", 0],
            "negative": ["3", 0], "latent_image": ["4", 0],
        },
    },
    "6": {
        "class_type": "VAEDecode",
        "inputs": {"samples": ["5", 0], "vae": ["1", 2]},
    },
    "7": {
        "class_type": "SaveImage",
        "inputs": {"filename_prefix": "E2E_session_mode", "images": ["6", 0]},
    },
}


def _get_runtime_python():
    """Get the ComfyUI Python interpreter for running generated scripts."""
    rt_python = Path(COMFYUI_PATH) / ".venv" / "bin" / "python"
    if rt_python.is_file():
        return str(rt_python)
    return sys.executable


def _export_session_workflow_in_runtime_env(
    workflow_json,
    execution_mode="session",
):
    """Export workflow via subprocess in ComfyUI runtime env.

    Re-enters the runtime interpreter so ``ComfyUItoPython`` can import
    ComfyUI's nodes.py (which requires torch, not available in the test venv).
    """
    runtime_python = _get_runtime_python()
    env = os.environ.copy()
    env["COMFYUI_PATH"] = COMFYUI_PATH
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT), env.get("PYTHONPATH", "")]).rstrip(
        os.pathsep
    )

    tmp_path = tempfile.mktemp(suffix=".py")

    try:
        result = subprocess.run(
            [
                runtime_python,
                str(Path(__file__).resolve().parents[0] / "runtime" / "run_runtime_validation.py"),
                "--internal-export",
                "text-to-image",
                "--execution-mode",
                execution_mode,
                "--generated-path",
                tmp_path,
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            output = (result.stderr or result.stdout or "").strip()
            if "Missing runtime dependency" not in output and "ModuleNotFoundError" not in output:
                classification = "repo regression"
            else:
                classification = "environment/setup failure"
            raise RuntimeError(
                f"Runtime export failed: [{classification}] {output}"
            )
        # Read generated code from the temp file (stdout is polluted by
        # ComfyUI runtime prints such as the sys.path line).
        return Path(tmp_path).read_text()
    finally:
        os.unlink(tmp_path)


def _export_workflow(execution_mode="oneshot"):
    """Export workflow to a string using ComfyUItoPython (unit tests, mock nodes)."""
    from comfyui_to_python import ComfyUItoPython
    output = StringIO()
    ComfyUItoPython(
        workflow=json.dumps(TEXT_TO_IMAGE_WORKFLOW),
        output_file=output,
        node_class_mappings=NODENAMES,
        execution_mode=execution_mode,
    )
    return output.getvalue()


class SessionCodeGenerationTest(unittest.TestCase):
    """Unit tests for session mode code generation."""

    def test_oneshot_code_has_bootstrap_helpers_no_session(self):
        """Oneshot mode: bootstrap/cleanup helpers present, no WorkflowSession class."""
        generated = _export_workflow("oneshot")
        ast.parse(generated)
        self.assertIn("bootstrap_comfyui_runtime()", generated)
        self.assertIn("cleanup_comfyui_runtime(", generated)
        self.assertNotIn("class WorkflowSession", generated)
        self.assertNotIn("session.run()", generated)

    def test_session_code_has_workflow_session_class_and_session_methods(self):
        """Session mode: WorkflowSession class with run() and close() present."""
        generated = _export_workflow("session")
        ast.parse(generated)
        self.assertIn("class WorkflowSession", generated)
        self.assertIn("def run(self)", generated)
        self.assertIn("def close(self, unload_models", generated)
        self.assertIn("session.run()", generated)
        self.assertIn("session.close(", generated)


class SessionModeExecutionTest(unittest.TestCase):
    """E2E tests for session mode script execution."""

    @unittest.skipIf(not Path(COMFYUI_PATH).is_dir(), "ComfyUI checkout not available")
    def test_oneshot_e2e_text_to_image(self):
        """Oneshot mode: generate and run text-to-image workflow, verify PNG output."""
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "oneshot.py"
            env = os.environ.copy()
            env["COMFYUI_PATH"] = COMFYUI_PATH
            env["PYTHONPATH"] = os.pathsep.join([str(ROOT), env.get("PYTHONPATH", "")])
            runtime_py = _get_runtime_python()

            # Export inside ComfyUI env so node mappings resolve
            generated = _export_session_workflow_in_runtime_env(
                json.dumps(TEXT_TO_IMAGE_WORKFLOW),
                execution_mode="oneshot",
            )
            script_path.write_text(generated)

            # Run
            result = subprocess.run(
                [runtime_py, str(script_path), "--cpu"],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=300,
            )
            self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")

            # Check output
            output_dir = Path(COMFYUI_PATH) / "output"
            new_outputs = list(output_dir.glob("E2E_text_to_image*.png"))
            self.assertTrue(len(new_outputs) > 0, "No PNG output produced")

    @unittest.skipIf(not Path(COMFYUI_PATH).is_dir(), "ComfyUI checkout not available")
    def test_session_e2e_text_to_image(self):
        """Session mode: generate session-mode script, verify WorkflowSession present and run."""
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "session.py"
            env = os.environ.copy()
            env["COMFYUI_PATH"] = COMFYUI_PATH
            env["PYTHONPATH"] = os.pathsep.join([str(ROOT), env.get("PYTHONPATH", "")])
            runtime_py = _get_runtime_python()

            # Export inside ComfyUI env
            generated = _export_session_workflow_in_runtime_env(
                json.dumps(TEXT_TO_IMAGE_WORKFLOW),
                execution_mode="session",
            )
            script_path.write_text(generated)

            # Verify code structure
            self.assertIn("class WorkflowSession", generated)

            # Run
            result = subprocess.run(
                [runtime_py, str(script_path), "--cpu"],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=300,
            )
            self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")

            # Check output
            output_dir = Path(COMFYUI_PATH) / "output"
            new_outputs = list(output_dir.glob("E2E_text_to_image*.png"))
            self.assertTrue(len(new_outputs) > 0, "No PNG output produced")

    @unittest.skipIf(not Path(COMFYUI_PATH).is_dir(), "ComfyUI checkout not available")
    def test_session_e2e_multiple_runs(self):
        """Session mode: generate script that calls session.run() 3x in a row, verify no crash."""
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "session_multi.py"
            env = os.environ.copy()
            env["COMFYUI_PATH"] = COMFYUI_PATH
            env["PYTHONPATH"] = os.pathsep.join([str(ROOT), env.get("PYTHONPATH", "")])
            runtime_py = _get_runtime_python()

            # Export session mode inside ComfyUI env
            generated = _export_session_workflow_in_runtime_env(
                json.dumps(TEXT_TO_IMAGE_WORKFLOW),
                execution_mode="session",
            )

            # Modify to run 3x
            modified = generated.replace(
                "        session.run()",
                "        session.run()\n        session.run()\n        session.run()",
            )
            script_path.write_text(modified)

            # Run
            result = subprocess.run(
                [runtime_py, str(script_path), "--cpu"],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=600,
            )
            self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")


if __name__ == "__main__":
    unittest.main()
