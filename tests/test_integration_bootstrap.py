import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "integration_tests" / "environment.toml"


class IntegrationBootstrapTests(unittest.TestCase):
    def test_environment_manifest_has_required_sections(self):
        manifest = tomllib.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        self.assertIn("workspace", manifest)
        self.assertIn("comfyui", manifest)
        self.assertIn("local_extension", manifest)
        self.assertIn("custom_nodes", manifest)
        self.assertIn("assets", manifest)

    def test_custom_node_entries_are_cloneable_git_specs(self):
        manifest = tomllib.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        custom_nodes = manifest["custom_nodes"]
        self.assertGreater(len(custom_nodes), 0)
        for entry in custom_nodes:
            self.assertTrue(entry["repo"].startswith("https://github.com/"))
            self.assertTrue(entry["path"].startswith("custom_nodes/"))

    def test_asset_entries_target_comfyui_relative_paths(self):
        manifest = tomllib.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        for entry in manifest["assets"]:
            self.assertNotIn("..", entry["path"])
            self.assertIn("/", entry["path"])


if __name__ == "__main__":
    unittest.main()
