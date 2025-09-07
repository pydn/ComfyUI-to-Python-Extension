#!/usr/bin/env python3
"""
Isolated test runner that avoids importing the root __init__.py file
"""
import os
import sys
import subprocess
import tempfile
import shutil
from pathlib import Path

def run_tests_isolated():
    """Run tests in an isolated environment to avoid ComfyUI import conflicts"""
    
    # Get the project root directory (parent of tests directory)
    current_dir = Path(__file__).parent.absolute()
    project_root = current_dir.parent
    
    # Create a temporary directory for isolated testing
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        # Copy only the test files and necessary modules to temp directory
        test_src = current_dir  # current_dir is already the tests directory
        test_dst = temp_path / "tests"
        shutil.copytree(test_src, test_dst)
        
        # Copy the main modules but not __init__.py
        modules_to_copy = [
            "comfyui_to_python.py",
            "comfyui_to_python_utils.py",
            "requirements.txt",
            "pyproject.toml",
            "run_tests.py"
        ]
        
        for module in modules_to_copy:
            src_file = project_root / module
            if src_file.exists():
                shutil.copy2(src_file, temp_path / module)
        
        # Note: tests/requirements.txt is already copied as part of the tests directory
        
        # Change to temp directory and run tests
        os.chdir(temp_path)
        
        # Run pytest
        cmd = [sys.executable, "-m", "pytest", "tests/", "-v"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        # Print results
        print("STDOUT:")
        print(result.stdout)
        if result.stderr:
            print("STDERR:")
            print(result.stderr)
        
        return result.returncode

if __name__ == "__main__":
    exit_code = run_tests_isolated()
    sys.exit(exit_code)
