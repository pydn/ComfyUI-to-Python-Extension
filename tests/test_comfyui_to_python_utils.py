import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from comfyui_to_python_utils import add_comfyui_directory_to_sys_path


class ComfyUIBootstrapTests(unittest.TestCase):
    def test_add_comfyui_directory_to_sys_path_prefers_comfyui_path(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            comfyui_root = Path(tmp_dir) / "Portable" / "ComfyUI"
            comfyui_root.mkdir(parents=True)
            for marker in ("main.py", "nodes.py", "folder_paths.py", "execution.py", "server.py"):
                (comfyui_root / marker).write_text("", encoding="utf-8")

            original_sys_path = list(sys.path)
            try:
                with patch.dict(os.environ, {"COMFYUI_PATH": str(comfyui_root)}, clear=False):
                    resolved = add_comfyui_directory_to_sys_path()
            finally:
                sys.path[:] = original_sys_path

        self.assertEqual(resolved, os.path.normpath(str(comfyui_root)))


if __name__ == "__main__":
    unittest.main()
