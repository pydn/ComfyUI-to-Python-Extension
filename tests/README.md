# ComfyUI-to-Python-Extension Test Suite

This directory contains the regression test suite for the ComfyUI-to-Python-Extension.

## Overview

The test suite validates the core functionality of the extension including:

1. **Simple Local Workflow** - Tests basic LoadImage → SaveImage workflow conversion
2. **Sync Custom Nodes** - Tests synchronous custom node workflow conversion  
3. **Async Custom Nodes** - Tests asynchronous custom node workflow conversion
4. **Parameterized Workflows** - Tests parameterized code generation
5. **Caching Functionality** - Tests node caching for constant values
6. **ComfyUI Auto-Discovery** - Tests automatic detection of local ComfyUI installation

## Requirements

- Python 3.8+
- Local ComfyUI installation
- pytest >= 7.0.0
- pytest-asyncio >= 0.21.0

## Running Tests

### Quick Start

From the project root directory:

```bash
python run_tests.py
```

Or from within the tests directory:

```bash
cd tests
python run_tests_isolated.py
```

### Manual Test Execution

```bash
# Install testing dependencies
pip install -r tests/requirements.txt

# Run all tests using isolated runner (recommended)
python tests/run_tests_isolated.py

# Run specific test files
cd tests
python -m pytest test_isolated.py -v
python -m pytest test_regression.py -v
```

### Command Line Options

```bash
python run_tests.py --help
```

- `-v, --verbose`: Verbose output
- `-k, --test-name`: Run only tests matching this name
- `-x, --failfast`: Stop on first failure
- `--skip-deps`: Skip dependency installation
- `--skip-setup`: Skip environment setup

## ComfyUI Auto-Discovery

The test suite automatically searches for ComfyUI installations in common locations:

- `~/ComfyUI`
- `~/Desktop/ComfyUI`
- `~/Documents/ComfyUI`
- `~/src/ComfyUI`
- `~/github/ComfyUI`
- `~/git/ComfyUI`
- `~/dev/ComfyUI`
- `~/projects/ComfyUI`
- `/opt/ComfyUI`
- `/usr/local/ComfyUI`
- Current directory and parent directories

## Test Structure

### `conftest.py`
Contains pytest fixtures and ComfyUI auto-discovery logic.

### `test_isolated.py`
Contains isolated tests that avoid ComfyUI import conflicts:
- Python syntax validation for main modules
- Basic functionality tests that don't require ComfyUI

### `test_custom_nodes.py`
Defines custom test nodes:
- `LoadTextSync` / `SaveTextSync` - Synchronous text processing nodes
- `LoadTextAsync` / `SaveTextAsync` - Asynchronous text processing nodes

### `test_regression.py`
Main regression test suite with comprehensive workflow testing.

## Custom Test Nodes

The test suite includes custom nodes specifically designed for testing:

### Synchronous Nodes
- **LoadTextSync**: Loads text synchronously
- **SaveTextSync**: Saves text to file synchronously

### Asynchronous Nodes  
- **LoadTextAsync**: Loads text asynchronously with optional delay
- **SaveTextAsync**: Saves text to file asynchronously with optional delay

These nodes allow testing of both sync and async workflow generation without requiring complex image processing dependencies.

## Expected Output

Successful test runs will show:

```
✅ ComfyUI auto-discovery test passed. Found at: /path/to/ComfyUI
✅ Simple workflow test passed. Generated file: /tmp/test_simple_workflow.py
✅ Sync custom nodes test passed. Generated file: /tmp/test_sync_workflow.py
✅ Async custom nodes test passed. Generated file: /tmp/test_async_workflow.py
✅ Parameterized workflow test passed. Generated file: /tmp/test_param_workflow.py
✅ Caching functionality test passed. Generated file: /tmp/test_cache_workflow.py
```

## Troubleshooting

### ComfyUI Not Found
If tests fail with "ComfyUI installation not found":
1. Ensure ComfyUI is installed locally
2. Check that it's in one of the searched locations
3. Verify main.py, nodes.py exist in the ComfyUI directory

### Import Errors
If you see import errors:
1. Ensure you're running from the project root directory
2. Check that all dependencies are installed
3. Verify ComfyUI path is correctly added to sys.path

### Test Failures
If specific tests fail:
1. Run with `-v` flag for detailed output
2. Check generated Python files for syntax errors
3. Ensure ComfyUI modules can be imported correctly

## Contributing

When adding new tests:
1. Add test methods to the appropriate test class
2. Use descriptive test names starting with `test_`
3. Include docstrings explaining what the test validates
4. Use appropriate fixtures for setup/teardown
5. Add assertions with clear error messages
