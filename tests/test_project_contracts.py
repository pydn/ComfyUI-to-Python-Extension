import tomllib
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


class ProjectContractsTest(unittest.TestCase):
    def test_project_declares_supported_python_floor(self):
        pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

        self.assertEqual(pyproject["project"]["requires-python"], ">=3.12")

    def test_readme_documents_python_support_and_default_save_filename(self):
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("This project supports Python 3.12 and newer.", readme)
        self.assertIn("default filename `workflow_api.py`", readme)

    def test_extension_import_path_requires_uv_sync_instead_of_running_install_py(self):
        init_text = (REPO_ROOT / "__init__.py").read_text(encoding="utf-8")

        self.assertIn("Run 'uv sync'", init_text)
        self.assertNotIn("spec_from_file_location", init_text)
        self.assertNotIn("Successfully installed. Hopefully, at least.", init_text)

    def test_frontend_save_flow_uses_deterministic_filename_without_prompt(self):
        save_as_script = (REPO_ROOT / "js" / "save-as-script.js").read_text(encoding="utf-8")

        self.assertIn('const DEFAULT_SCRIPT_FILENAME = "workflow_api.py";', save_as_script)
        self.assertNotIn("prompt(", save_as_script)

