# Testing Guide

This document explains how to run tests for the ComfyUI-to-Python-Extension.

## Quick Start

### Install Testing Dependencies
```bash
pip install -r tests/requirements.txt
```

### From Project Root
```bash
python run_tests.py
```

### From Tests Directory
```bash
cd tests
python run_tests_isolated.py
```

## Test Structure

```
ComfyUI-to-Python-Extension/
├── requirements.txt                # Runtime dependencies only
├── run_tests.py                    # Simple test runner (calls isolated runner)
└── tests/                          # All testing functionality
    ├── conftest.py                 # Pytest configuration and fixtures
    ├── pytest.ini                 # Pytest settings
    ├── requirements.txt            # Testing dependencies
    ├── run_tests_isolated.py       # Isolated test runner (avoids import conflicts)
    ├── README.md                   # Detailed testing documentation
    ├── test_custom_nodes.py        # Custom node definitions for testing
    ├── test_isolated.py            # Isolated functionality tests
    └── test_regression.py          # Regression tests (require ComfyUI)
```

## Test Categories

### ✅ Always Run (1 test)
- **Syntax Tests** - Validate Python syntax of main modules

### ⏭️ Skipped in Isolated Mode (5+ tests)
- **Integration Tests** - Require full ComfyUI environment
- **Workflow Conversion Tests** - Need ComfyUI modules
- **Custom Node Tests** - Require ComfyUI integration

## Why Isolated Testing?

The isolated test runner solves import conflicts between:
- ComfyUI's `protocol` module requirements
- System-installed `protocol` packages
- pytest's import discovery process

## Test Results

**Expected Results:**
- ✅ **1 passed, 5+ skipped** - Perfect!
- ✅ **Exit code: 0** - Success
- ⚠️ **Any failures** - Investigate

## Troubleshooting

If tests fail:
1. Check that all required files exist
2. Verify Python syntax in main modules
3. Ensure ComfyUI is properly installed (for integration tests)
4. Check that file permissions are correct (`chmod +x run_tests.py`)

## Development

When adding new tests:
- Add isolated unit tests to `test_isolated.py` (always run, no ComfyUI imports)
- Add integration tests to `test_regression.py` (require ComfyUI)
- Update this documentation as needed
