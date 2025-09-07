#!/usr/bin/env python3
"""
Simple test runner that calls the isolated test runner in the tests directory
"""
import sys
import subprocess
from pathlib import Path

def main():
    """Run the isolated test runner"""
    # Get the path to the isolated test runner
    project_root = Path(__file__).parent.absolute()
    isolated_runner = project_root / "tests" / "run_tests_isolated.py"
    
    if not isolated_runner.exists():
        print("Error: Isolated test runner not found at tests/run_tests_isolated.py")
        return 1
    
    # Run the isolated test runner
    try:
        result = subprocess.run([sys.executable, str(isolated_runner)], 
                              cwd=project_root)
        return result.returncode
    except Exception as e:
        print(f"Error running tests: {e}")
        return 1

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
