import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

from tests.runtime.run_runtime_validation import (
    FixtureConfig,
    ModelRequirement,
    ValidationFailure,
    check_models,
    ensure_runtime_path,
    execute_generated_python,
    load_fixture_names,
    parse_png_info,
    validate_generated_python,
)


def make_png_bytes(
    width: int,
    height: int,
    text_chunks: list[tuple[bytes, bytes]] | None = None,
) -> bytes:
    def chunk(chunk_type: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
        return (
            struct.pack(">I", len(data))
            + chunk_type
            + data
            + struct.pack(">I", crc)
        )

    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    text_chunks = text_chunks or []
    idat = chunk(
        b"IDAT",
        zlib.compress(b"\x00" + (b"\x00\x00\x00" * width)),
    )
    return b"".join(
        [
            b"\x89PNG\r\n\x1a\n",
            ihdr,
            *[chunk(chunk_type, payload) for chunk_type, payload in text_chunks],
            idat,
            chunk(b"IEND", b""),
        ]
    )


class RuntimeValidationHarnessTest(unittest.TestCase):
    def test_load_fixture_names_all_returns_registered_names(self):
        fixture_names = load_fixture_names("all")

        self.assertGreaterEqual(len(fixture_names), 4)
        self.assertEqual(fixture_names[0], "upscale-model-loader")
        self.assertIn("unsafe-kwargs", fixture_names)

    def test_load_fixture_names_rejects_unknown_fixture(self):
        with self.assertRaises(ValidationFailure) as context:
            load_fixture_names("missing-fixture")

        self.assertEqual(context.exception.classification, "fixture bug")
        self.assertIn("Unknown fixture", context.exception.message)

    def test_ensure_runtime_path_fast_tier_returns_env_without_validation(self):
        with patch.dict("os.environ", {"COMFYUI_PATH": "/does/not/exist"}, clear=False):
            runtime_path = ensure_runtime_path("fast")

        self.assertEqual(runtime_path, "/does/not/exist")

    @patch("tests.runtime.run_runtime_validation.get_comfyui_path", return_value="")
    def test_ensure_runtime_path_runtime_tier_requires_valid_checkout(self, _mock_path):
        with self.assertRaises(ValidationFailure) as context:
            ensure_runtime_path("runtime")

        self.assertEqual(context.exception.classification, "environment/setup failure")
        self.assertIn("Could not find a valid ComfyUI checkout", context.exception.message)

    def test_check_models_returns_only_missing_requirements(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_path = Path(tmpdir)
            present_dir = runtime_path / "models" / "checkpoints"
            present_dir.mkdir(parents=True)
            (present_dir / "present.safetensors").write_text("ok", encoding="utf-8")
            fixture = FixtureConfig(
                name="model-checks",
                path=Path("unused.json"),
                model_requirements=(
                    ModelRequirement(
                        filename="present.safetensors",
                        relative_dir="models/checkpoints",
                        source_url="https://example.invalid/present",
                    ),
                    ModelRequirement(
                        filename="missing.safetensors",
                        relative_dir="models/checkpoints",
                        source_url="https://example.invalid/missing",
                    ),
                ),
            )

            missing = check_models(fixture, str(runtime_path))

        self.assertEqual([item.filename for item in missing], ["missing.safetensors"])

    def test_validate_generated_python_accepts_valid_python(self):
        validate_generated_python("value = 1\n", "valid-fixture")

    def test_validate_generated_python_reports_syntax_regression(self):
        with self.assertRaises(ValidationFailure) as context:
            validate_generated_python("def broken(:\n", "broken-fixture")

        self.assertEqual(context.exception.classification, "repo regression")
        self.assertIn("broken-fixture", context.exception.message)

    def test_parse_png_info_reads_dimensions_and_text_chunks(self):
        compressed_text = zlib.compress(b"workflow data")
        png_bytes = make_png_bytes(
            width=3,
            height=2,
            text_chunks=[
                (b"tEXt", b"prompt\x00hello"),
                (b"zTXt", b"workflow\x00\x00" + compressed_text),
                (b"iTXt", b"comment\x00\x00\x00\x00\x00unicode text"),
            ],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "artifact.png"
            image_path.write_bytes(png_bytes)

            width, height, metadata = parse_png_info(image_path)

        self.assertEqual((width, height), (3, 2))
        self.assertEqual(metadata["prompt"], "hello")
        self.assertEqual(metadata["workflow"], "workflow data")
        self.assertEqual(metadata["comment"], "unicode text")

    def test_parse_png_info_rejects_non_png_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "artifact.bin"
            image_path.write_bytes(b"not-a-png")

            with self.assertRaises(ValidationFailure) as context:
                parse_png_info(image_path)

        self.assertEqual(context.exception.classification, "environment/setup failure")
        self.assertIn("Expected PNG output", context.exception.message)

    def test_parse_png_info_requires_dimensions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "artifact.png"
            image_path.write_bytes(
                b"\x89PNG\r\n\x1a\n"
                + struct.pack(">I", 0)
                + b"IEND"
                + struct.pack(">I", 0)
            )

            with self.assertRaises(ValidationFailure) as context:
                parse_png_info(image_path)

        self.assertEqual(context.exception.classification, "environment/setup failure")
        self.assertIn("Could not read PNG dimensions", context.exception.message)

    @patch("tests.runtime.run_runtime_validation.get_runtime_python", return_value="/usr/bin/python")
    @patch("tests.runtime.run_runtime_validation.subprocess.run")
    def test_execute_generated_python_classifies_missing_torch_as_environment_failure(
        self,
        mock_run,
        _mock_runtime_python,
    ):
        mock_run.return_value.returncode = 1
        mock_run.return_value.stderr = "ModuleNotFoundError: No module named 'torch'"
        mock_run.return_value.stdout = ""
        fixture = FixtureConfig(
            name="runtime-fixture",
            path=Path("unused.json"),
            runtime_capable=True,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "output").mkdir()
            with self.assertRaises(ValidationFailure) as context:
                execute_generated_python("print('hello')\n", fixture, tmpdir)

        self.assertEqual(context.exception.classification, "environment/setup failure")

    @patch("tests.runtime.run_runtime_validation.get_runtime_python", return_value="/usr/bin/python")
    @patch("tests.runtime.run_runtime_validation.subprocess.run")
    def test_execute_generated_python_classifies_missing_files_as_environment_failure(
        self,
        mock_run,
        _mock_runtime_python,
    ):
        mock_run.return_value.returncode = 1
        mock_run.return_value.stderr = "No such file or directory: missing.png"
        mock_run.return_value.stdout = ""
        fixture = FixtureConfig(
            name="runtime-fixture",
            path=Path("unused.json"),
            runtime_capable=True,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "output").mkdir()
            with self.assertRaises(ValidationFailure) as context:
                execute_generated_python("print('hello')\n", fixture, tmpdir)

        self.assertEqual(context.exception.classification, "environment/setup failure")

    @patch("tests.runtime.run_runtime_validation.get_runtime_python", return_value="/usr/bin/python")
    @patch("tests.runtime.run_runtime_validation.subprocess.run")
    def test_execute_generated_python_classifies_other_failures_as_repo_regression(
        self,
        mock_run,
        _mock_runtime_python,
    ):
        mock_run.return_value.returncode = 1
        mock_run.return_value.stderr = "ValueError: broken workflow"
        mock_run.return_value.stdout = ""
        fixture = FixtureConfig(
            name="runtime-fixture",
            path=Path("unused.json"),
            runtime_capable=True,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "output").mkdir()
            with self.assertRaises(ValidationFailure) as context:
                execute_generated_python("print('hello')\n", fixture, tmpdir)

        self.assertEqual(context.exception.classification, "repo regression")

    @patch("tests.runtime.run_runtime_validation.get_runtime_python", return_value="/usr/bin/python")
    @patch("tests.runtime.run_runtime_validation.subprocess.run")
    def test_execute_generated_python_requires_fresh_matching_artifact(
        self,
        mock_run,
        _mock_runtime_python,
    ):
        mock_run.return_value.returncode = 0
        mock_run.return_value.stderr = ""
        mock_run.return_value.stdout = ""
        fixture = FixtureConfig(
            name="runtime-fixture",
            path=Path("unused.json"),
            runtime_capable=True,
            filename_prefix="expected_prefix",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "output").mkdir()
            with self.assertRaises(ValidationFailure) as context:
                execute_generated_python("print('hello')\n", fixture, tmpdir)

        self.assertEqual(context.exception.classification, "repo regression")
        self.assertIn("did not produce a new output file", context.exception.message)

    @patch("tests.runtime.run_runtime_validation.get_runtime_python", return_value="/usr/bin/python")
    @patch("tests.runtime.run_runtime_validation.validate_output_artifact")
    @patch("tests.runtime.run_runtime_validation.subprocess.run")
    def test_execute_generated_python_validates_newest_matching_artifact(
        self,
        mock_run,
        mock_validate_output,
        _mock_runtime_python,
    ):
        mock_run.return_value.returncode = 0
        mock_run.return_value.stderr = ""
        mock_run.return_value.stdout = ""
        fixture = FixtureConfig(
            name="runtime-fixture",
            path=Path("unused.json"),
            runtime_capable=True,
            filename_prefix="expected_prefix",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "output"
            output_dir.mkdir()
            older = output_dir / "expected_prefix_00001_.png"
            older.write_bytes(make_png_bytes(1, 1))
            with patch(
                "tests.runtime.run_runtime_validation.subprocess.run",
                side_effect=self._write_runtime_artifact(mock_run.return_value, output_dir),
            ):
                execute_generated_python("print('hello')\n", fixture, tmpdir)

        validated_path = mock_validate_output.call_args[0][1]
        self.assertEqual(validated_path.name, "expected_prefix_00002_.png")

    @staticmethod
    def _write_runtime_artifact(result, output_dir: Path):
        def side_effect(*_args, **_kwargs):
            (output_dir / "expected_prefix_00002_.png").write_bytes(make_png_bytes(2, 2))
            return result

        return side_effect


if __name__ == "__main__":
    unittest.main()
