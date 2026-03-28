import argparse
import ast
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Callable

from comfyui_to_python_utils import get_comfyui_path

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "runtime"
GENERATED_DIR = ROOT / "tests" / "runtime" / "generated"
COMFYUI_OUTPUT_DIRNAME = "output"
COMFYUI_INPUT_DIRNAME = "input"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class ValidationFailure(RuntimeError):
    def __init__(self, classification: str, message: str):
        super().__init__(message)
        self.classification = classification
        self.message = message


@dataclass(frozen=True)
class FixtureConfig:
    name: str
    path: Path
    mapping_factory: Callable[[], dict] | None = None
    fast_mapping_factory: Callable[[], dict] | None = None
    runtime_capable: bool = False
    filename_prefix: str | None = None
    expected_min_dimensions: tuple[int, int] | None = None
    metadata_markers: tuple[str, ...] = ()
    model_requirements: tuple["ModelRequirement", ...] = ()
    staged_inputs: tuple["StagedInput", ...] = ()


@dataclass(frozen=True)
class ModelRequirement:
    filename: str
    relative_dir: str
    source_url: str


@dataclass(frozen=True)
class StagedInput:
    source_path: Path
    destination_name: str


class FlexibleNode:
    CATEGORY = "utils"
    FUNCTION = "run"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "safe_name": ("STRING",),
            }
        }

    def run(self, **kwargs):
        return (kwargs,)


class RegexReplace:
    CATEGORY = "utils"
    FUNCTION = "replace"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING",),
                "pattern": ("STRING",),
                "replace": ("STRING",),
            }
        }

    def replace(self, text, pattern, replace):
        return (text,)


class PassthroughText:
    CATEGORY = "utils"
    FUNCTION = "run"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING",),
            }
        }

    def run(self, text):
        return (text,)


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


class SaveImageNode:
    CATEGORY = "image"
    FUNCTION = "save_images"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "filename_prefix": ("STRING",),
            }
        }

    def save_images(self, images, filename_prefix):
        return ()


FIXTURES = {
    # Runtime-capable fixtures are exported inside a real ComfyUI checkout and
    # then executed end-to-end. Fast fixtures use local stub mappings so the
    # exporter can be validated without importing the full runtime.
    "upscale-model-loader": FixtureConfig(
        name="upscale-model-loader",
        path=FIXTURE_DIR / "upscale-model-loader.json",
        fast_mapping_factory=lambda: {
            "LoadImage": LoadImage,
            "UpscaleModelLoader": UpscaleModelLoader,
            "ImageUpscaleWithModel": ImageUpscaleWithModel,
            "SaveImage": SaveImageNode,
        },
        runtime_capable=True,
        filename_prefix="E2E_upscale_model_loader",
        expected_min_dimensions=(1000, 1000),
        metadata_markers=("UpscaleModelLoader", "E2E_upscale_model_loader"),
        model_requirements=(
            ModelRequirement(
                filename="RealESRGAN_x4plus.safetensors",
                relative_dir="models/upscale_models",
                source_url="https://huggingface.co/Comfy-Org/Real-ESRGAN_repackaged/resolve/main/RealESRGAN_x4plus.safetensors",
            ),
        ),
        staged_inputs=(
            StagedInput(
                source_path=ROOT / "images" / "save_as_script.png",
                destination_name="e2e_upscale_input.png",
            ),
        ),
    ),
    "text-to-image": FixtureConfig(
        name="text-to-image",
        path=FIXTURE_DIR / "text-to-image.json",
        runtime_capable=True,
        filename_prefix="E2E_text_to_image",
        expected_min_dimensions=(512, 512),
        metadata_markers=("a small cottage in a meadow", "CheckpointLoaderSimple"),
        model_requirements=(
            ModelRequirement(
                filename="v1-5-pruned-emaonly-fp16.safetensors",
                relative_dir="models/checkpoints",
                source_url="https://huggingface.co/Comfy-Org/stable-diffusion-v1-5-archive/resolve/main/v1-5-pruned-emaonly-fp16.safetensors",
            ),
        ),
    ),
    "unsafe-kwargs": FixtureConfig(
        name="unsafe-kwargs",
        path=FIXTURE_DIR / "unsafe-kwargs.json",
        mapping_factory=lambda: {"FlexibleNode": FlexibleNode},
    ),
    "subgraph-identifiers": FixtureConfig(
        name="subgraph-identifiers",
        path=FIXTURE_DIR / "subgraph-identifiers.json",
        mapping_factory=lambda: {
            "RegexReplace": RegexReplace,
            "PassthroughText": PassthroughText,
        },
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run fast or runtime validation for committed fixtures."
    )
    parser.add_argument(
        "--tier",
        choices=("fast", "runtime"),
        help="Validation tier to run.",
    )
    parser.add_argument(
        "--fixture",
        default="all",
        help="Fixture name or 'all'.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute generated Python for runtime-capable fixtures.",
    )
    parser.add_argument(
        "--print-download-plan",
        action="store_true",
        help="Print model download commands for missing models.",
    )
    parser.add_argument(
        "--internal-export",
        choices=tuple(FIXTURES.keys()),
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--generated-path",
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()
    if not args.internal_export and not args.tier:
        parser.error("--tier is required unless --internal-export is used.")
    return args


def load_fixture_names(selection: str) -> list[str]:
    if selection == "all":
        return list(FIXTURES.keys())
    if selection not in FIXTURES:
        raise ValidationFailure("fixture bug", f"Unknown fixture '{selection}'.")
    return [selection]


def ensure_runtime_path(tier: str) -> str:
    if tier == "runtime":
        runtime_path = get_comfyui_path()
    else:
        return os.environ.get("COMFYUI_PATH", "")

    if not runtime_path or not Path(runtime_path).is_dir():
        raise ValidationFailure(
            "environment/setup failure",
            "Could not find a valid ComfyUI checkout for runtime validation. "
            "Set COMFYUI_PATH or run the tests from a location where a "
            "parent directory contains ComfyUI.",
        )

    return str(runtime_path)


def get_runtime_python(runtime_path: str) -> str:
    runtime_python = Path(runtime_path) / ".venv" / "bin" / "python"
    if runtime_python.is_file():
        return str(runtime_python)
    return sys.executable


def get_fixture(fixture_name: str) -> FixtureConfig:
    return FIXTURES[fixture_name]


def check_models(fixture: FixtureConfig, runtime_path: str) -> list[ModelRequirement]:
    runtime_root = Path(runtime_path)
    missing = []
    for requirement in fixture.model_requirements:
        target = runtime_root / requirement.relative_dir / requirement.filename
        if not target.is_file():
            missing.append(requirement)
    return missing


def print_download_plan(fixture: FixtureConfig, runtime_path: str) -> None:
    runtime_root = Path(runtime_path)
    for requirement in check_models(fixture, runtime_path):
        target_dir = runtime_root / requirement.relative_dir
        print(
            "download:",
            f"mkdir -p {target_dir} && curl -L {requirement.source_url} -o {target_dir / requirement.filename}",
        )


def stage_inputs(fixture: FixtureConfig, runtime_path: str) -> None:
    runtime_input_dir = Path(runtime_path) / COMFYUI_INPUT_DIRNAME
    runtime_input_dir.mkdir(parents=True, exist_ok=True)
    for staged_input in fixture.staged_inputs:
        if not staged_input.source_path.is_file():
            raise ValidationFailure(
                "fixture bug",
                f"Missing staged input source {staged_input.source_path} for {fixture.name}.",
            )
        shutil.copyfile(
            staged_input.source_path,
            runtime_input_dir / staged_input.destination_name,
        )


def export_workflow(
    fixture: FixtureConfig,
    tier: str,
    runtime_path: str,
) -> tuple[str, str]:
    from comfyui_to_python import ComfyUItoPython

    workflow = fixture.path.read_text(encoding="utf-8")
    output = StringIO()
    kwargs = {
        "workflow": workflow,
        "output_file": output,
    }
    if tier == "fast" and fixture.fast_mapping_factory is not None:
        kwargs["node_class_mappings"] = fixture.fast_mapping_factory()
    elif fixture.mapping_factory is not None:
        kwargs["node_class_mappings"] = fixture.mapping_factory()
    else:
        os.environ["COMFYUI_PATH"] = runtime_path

    try:
        ComfyUItoPython(**kwargs)
    except ModuleNotFoundError as exc:
        missing_module = exc.name or "unknown"
        raise ValidationFailure(
            "environment/setup failure",
            f"Missing runtime dependency '{missing_module}' while exporting {fixture.name}.",
        ) from exc
    except KeyError as exc:
        raise ValidationFailure(
            "repo regression",
            f"Exporter failed to resolve workflow data for {fixture.name}: {exc}",
        ) from exc
    except Exception as exc:
        raise ValidationFailure(
            "repo regression",
            f"Exporter failed for {fixture.name}: {exc}",
        ) from exc

    return workflow, output.getvalue()


def export_workflow_in_runtime_env(fixture: FixtureConfig, runtime_path: str) -> str:
    runtime_python = get_runtime_python(runtime_path)
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    generated_path = GENERATED_DIR / f"{fixture.name}.py"
    env = os.environ.copy()
    env["COMFYUI_PATH"] = runtime_path
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT), env.get("PYTHONPATH", "")]).rstrip(
        os.pathsep
    )
    # Re-enter this script under the runtime interpreter so export happens with
    # the target ComfyUI checkout on sys.path, not just the repo's current venv.
    result = subprocess.run(
        [
            runtime_python,
            str(Path(__file__).resolve()),
            "--internal-export",
            fixture.name,
            "--generated-path",
            str(generated_path),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        output = (result.stderr or result.stdout or "").strip()
        classification = "environment/setup failure"
        if (
            "Missing runtime dependency" not in output
            and "ModuleNotFoundError" not in output
        ):
            classification = "repo regression"
        raise ValidationFailure(
            classification,
            f"Runtime export failed for {fixture.name}: {output}",
        )
    return generated_path.read_text(encoding="utf-8")


def validate_generated_python(generated_code: str, fixture_name: str) -> None:
    try:
        ast.parse(generated_code)
    except SyntaxError as exc:
        raise ValidationFailure(
            "repo regression",
            f"Generated Python is not valid for {fixture_name}: {exc}",
        ) from exc


def parse_png_info(image_path: Path) -> tuple[int, int, dict[str, str]]:
    with image_path.open("rb") as handle:
        signature = handle.read(8)
        if signature != b"\x89PNG\r\n\x1a\n":
            raise ValidationFailure(
                "environment/setup failure",
                f"Expected PNG output for {image_path.name}, got a different file format.",
            )

        width = height = None
        text_data: dict[str, str] = {}
        while True:
            length_bytes = handle.read(4)
            if not length_bytes:
                break
            length = struct.unpack(">I", length_bytes)[0]
            chunk_type = handle.read(4)
            chunk_data = handle.read(length)
            handle.read(4)

            if chunk_type == b"IHDR":
                width, height = struct.unpack(">II", chunk_data[:8])
            elif chunk_type == b"tEXt":
                key, value = chunk_data.split(b"\x00", 1)
                text_data[key.decode("latin-1")] = value.decode("latin-1")
            elif chunk_type == b"zTXt":
                key, compressed = chunk_data.split(b"\x00", 1)
                text_data[key.decode("latin-1")] = zlib.decompress(
                    compressed[1:]
                ).decode("latin-1")
            elif chunk_type == b"iTXt":
                parts = chunk_data.split(b"\x00", 5)
                if len(parts) == 6:
                    key = parts[0].decode("utf-8")
                    compressed_flag = parts[1]
                    value = parts[5]
                    if compressed_flag == b"\x01":
                        value = zlib.decompress(value)
                    text_data[key] = value.decode("utf-8")
            elif chunk_type == b"IEND":
                break

        if width is None or height is None:
            raise ValidationFailure(
                "environment/setup failure",
                f"Could not read PNG dimensions from {image_path.name}.",
            )

    return width, height, text_data


def validate_output_artifact(
    fixture: FixtureConfig,
    output_path: Path,
) -> None:
    # Read PNG metadata directly so artifact validation does not depend on
    # optional imaging libraries inside the runtime environment.
    width, height, metadata = parse_png_info(output_path)

    if fixture.expected_min_dimensions is not None:
        min_width, min_height = fixture.expected_min_dimensions
        if width < min_width or height < min_height:
            raise ValidationFailure(
                "repo regression",
                f"Output dimensions for {fixture.name} were {width}x{height}, expected at least {min_width}x{min_height}.",
            )

    metadata_blob = "\n".join(
        [output_path.name] + [f"{key}={value}" for key, value in metadata.items()]
    )
    for marker in fixture.metadata_markers:
        if marker not in metadata_blob:
            raise ValidationFailure(
                "repo regression",
                f"Output metadata for {fixture.name} did not contain expected marker '{marker}'.",
            )


def execute_generated_python(
    generated_code: str,
    fixture: FixtureConfig,
    runtime_path: str,
) -> None:
    if not fixture.runtime_capable:
        raise ValidationFailure(
            "fixture bug",
            f"Fixture {fixture.name} is not marked runtime-capable.",
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir) / f"{fixture.name}.py"
        tmp_path.write_text(generated_code, encoding="utf-8")
        output_dir = Path(runtime_path) / COMFYUI_OUTPUT_DIRNAME
        # Compare against the pre-run snapshot so validation can prove this
        # execution created a fresh artifact instead of reusing an old output.
        existing_outputs = set(output_dir.glob("*.png"))
        env = os.environ.copy()
        env["COMFYUI_PATH"] = runtime_path
        env["PYTHONPATH"] = os.pathsep.join(
            [str(ROOT), env.get("PYTHONPATH", "")]
        ).rstrip(os.pathsep)
        runtime_python = get_runtime_python(runtime_path)

        result = subprocess.run(
            [runtime_python, str(tmp_path)],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            if fixture.filename_prefix is None:
                return
            new_outputs = [
                path
                for path in output_dir.glob(f"{fixture.filename_prefix}*.png")
                if path not in existing_outputs
            ]
            if not new_outputs:
                raise ValidationFailure(
                    "repo regression",
                    f"Generated script for {fixture.name} did not produce a new output file with prefix {fixture.filename_prefix}.",
                )
            newest_output = max(new_outputs, key=lambda path: path.stat().st_mtime)
            validate_output_artifact(fixture, newest_output)
            return

        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        output = stderr or stdout or "generated script exited with a non-zero status"
        lower_output = output.lower()

        if "no module named 'torch'" in lower_output:
            classification = "environment/setup failure"
        elif "no such file or directory" in lower_output or "not found" in lower_output:
            classification = "environment/setup failure"
        else:
            classification = "repo regression"

        raise ValidationFailure(
            classification,
            f"Generated script execution failed for {fixture.name}: {output}",
        )


def run_fixture(fixture: FixtureConfig, tier: str, execute: bool, runtime_path: str) -> str:
    if tier == "fast":
        _, generated_code = export_workflow(fixture, tier, runtime_path)
    else:
        missing_models = check_models(fixture, runtime_path)
        if missing_models:
            raise ValidationFailure(
                "model provisioning failure",
                "Missing models for "
                f"{fixture.name}: "
                + ", ".join(
                    f"{item.relative_dir}/{item.filename}" for item in missing_models
                ),
            )
        stage_inputs(fixture, runtime_path)
        generated_code = export_workflow_in_runtime_env(fixture, runtime_path)
    validate_generated_python(generated_code, fixture.name)

    # Fast keeps execution opt-in because its stub node mappings are intended for
    # export coverage only. Runtime always executes the generated script.
    should_execute = execute or tier == "runtime"
    if should_execute and tier == "runtime":
        execute_generated_python(generated_code, fixture, runtime_path)

    return "pass"


def main() -> int:
    args = parse_args()

    if args.internal_export:
        fixture = get_fixture(args.internal_export)
        output_path = Path(args.generated_path)
        _, generated_code = export_workflow(
            fixture=fixture,
            tier="runtime",
            runtime_path=os.environ.get("COMFYUI_PATH", ""),
        )
        output_path.write_text(generated_code, encoding="utf-8")
        return 0

    try:
        runtime_path = ensure_runtime_path(args.tier)
        fixture_names = load_fixture_names(args.fixture)
        requested = [FIXTURES[name] for name in fixture_names]

        if args.tier == "fast":
            requested = [
                fixture
                for fixture in requested
                if fixture.fast_mapping_factory is not None
                or fixture.mapping_factory is not None
            ]
            if not requested:
                raise ValidationFailure(
                    "fixture bug",
                    "No selected fixtures are fast-tier compatible.",
                )
        elif args.tier == "runtime":
            requested = [fixture for fixture in requested if fixture.runtime_capable]
            if not requested:
                raise ValidationFailure(
                    "fixture bug",
                    "No selected fixtures are runtime-capable for this tier.",
                )

        failures: list[tuple[str, str, str]] = []
        for fixture in requested:
            try:
                if args.print_download_plan and args.tier == "runtime":
                    missing_models = check_models(fixture, runtime_path)
                    for requirement in missing_models:
                        target_dir = Path(runtime_path) / requirement.relative_dir
                        print(
                            "download:",
                            f"mkdir -p {target_dir} && curl -L {requirement.source_url} -o {target_dir / requirement.filename}",
                        )
                    if missing_models:
                        print(f"{fixture.name}: download-plan")
                        continue
                status = run_fixture(fixture, args.tier, args.execute, runtime_path)
                print(f"{fixture.name}: {status}")
            except ValidationFailure as exc:
                failures.append((fixture.name, exc.classification, exc.message))
                print(
                    f"{fixture.name}: fail ({exc.classification})",
                    file=sys.stderr,
                )
                print(exc.message, file=sys.stderr)
        if failures:
            classifications = ", ".join(
                f"{name}={classification}" for name, classification, _ in failures
            )
            print(f"classification: {classifications}", file=sys.stderr)
            return 1
    except ValidationFailure as exc:
        print(f"classification: {exc.classification}", file=sys.stderr)
        print(exc.message, file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
