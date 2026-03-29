# Tests

This directory contains two test paths:

- unit tests for exporter behavior
- runtime validation for committed workflow fixtures

Use the lightweight path for routine contributor validation, and use the runtime path when you need end-to-end confidence against a real ComfyUI checkout.

## Prerequisites

- Run commands from the repo root.
- Use `uv` for all project commands.
- Install the repo environment first:

```bash
uv sync
```

- Runtime validation also needs a working ComfyUI checkout.
  Set `COMFYUI_PATH` to that checkout, or run the tests from a location where a parent directory contains `ComfyUI`.
- Runtime-tier tests do not download missing models automatically.
  If a required model is missing, the fixture fails with `model provisioning failure`.
  Use `--print-download-plan` to print the manual download commands.

### Runtime Model Requirements

The current runtime-capable fixtures require these model files in the target ComfyUI checkout:

- `text-to-image`: `models/checkpoints/v1-5-pruned-emaonly-fp16.safetensors`
- `upscale-model-loader`: `models/upscale_models/RealESRGAN_x4plus.safetensors`

## Unit Tests

Run the exporter-focused unit test module:

```bash
uv run python -m unittest tests.test_upscale_model_loader_export
```

Run the runtime-harness unit test module:

```bash
uv run python -m unittest tests.test_runtime_validation_harness
```

Run all `unittest`-discoverable tests under `tests`:

```bash
uv run python -m unittest discover -s tests
```

## Runtime Tests

The runtime harness lives at `tests/runtime/run_runtime_validation.py`.

### Fast Tier

Fast tier validates export behavior against committed fixtures without requiring a full ComfyUI runtime for every fixture.
This is the recommended default validation lane for routine changes.

Run all fast-tier compatible fixtures:

```bash
uv run python tests/runtime/run_runtime_validation.py --tier fast --fixture all
```

Run one fixture:

```bash
uv run python tests/runtime/run_runtime_validation.py --tier fast --fixture unsafe-kwargs
```

### Runtime Tier

Runtime tier exports inside a real ComfyUI checkout and executes generated Python for runtime-capable fixtures.
This is the heavier validation lane for changes that need end-to-end runtime confidence.

Run all runtime-capable fixtures:

```bash
uv run python tests/runtime/run_runtime_validation.py --tier runtime --fixture all
```

Run one runtime-capable fixture:

```bash
uv run python tests/runtime/run_runtime_validation.py --tier runtime --fixture text-to-image
```

Print download commands for missing models instead of failing immediately:

```bash
uv run python tests/runtime/run_runtime_validation.py --tier runtime --fixture all --print-download-plan
```

## Runtime Fixture Names

Current committed fixtures:

- `upscale-model-loader`
- `text-to-image`
- `unsafe-kwargs`
- `subgraph-identifiers`
- `reused-node-class-branches`
- `secondary-output-selection`

Notes:

- `--tier runtime` only runs fixtures marked runtime-capable.
- `--tier fast` only runs fixtures with local test mappings.
- `reused-node-class-branches` protects repeated node-class usage and branch wiring in the fast tier.
- `secondary-output-selection` protects non-zero output index wiring in the fast tier.

## Troubleshooting

- `No module named ...`:
  run `uv sync` in this repo, and for runtime-tier failures also make sure the target ComfyUI checkout has its own dependencies installed.
- `Could not find a valid ComfyUI checkout for runtime validation.`:
  set `COMFYUI_PATH` to your ComfyUI checkout, or run the tests from a directory layout where a parent folder contains `ComfyUI`.
- `Missing models for ...`:
  runtime-tier tests do not fetch models for you. Rerun with `--print-download-plan` to print the expected `curl` commands and target model directories, then install the files manually.
- `No selected fixtures are runtime-capable for this tier.`:
  choose a runtime-capable fixture such as `text-to-image` or `upscale-model-loader`.
- Generated script execution fails because files or models are missing:
  confirm the required models exist under the target ComfyUI checkout and that any staged inputs can be copied into its `input/` directory.
