# Runtime Validation

This repo has two validation tiers:

- `fast`
- `runtime`

Use `uv` for repo commands.

## Local Runtime Paths

Pinned ComfyUI checkout:

- `/home/peyton/code/ComfyUI`

The runtime harness uses `COMFYUI_PATH` to point generated scripts and export logic at the target ComfyUI checkout.
For full E2E runtime execution, the harness prefers the ComfyUI checkout's own Python interpreter at `/home/peyton/code/ComfyUI/.venv/bin/python` when available.

## Fixtures

Committed runtime fixtures live in:

- [tests/fixtures/runtime](/home/peyton/code/ComfyUI-to-Python-Extension/tests/fixtures/runtime)

Current fixtures:

- `upscale-model-loader`
- `text-to-image`
- `unsafe-kwargs`
- `subgraph-identifiers`

Runtime-tier fixtures are based on official core ComfyUI workflow shapes:

- the Image Upscale workflow
- the Text to Image workflow

Sources:

- https://docs.comfy.org/tutorials/basic/upscale
- https://docs.comfy.org/tutorials/basic/text-to-image

## Commands

### Fast

Run exporter-only validation without a real ComfyUI runtime:

```bash
uv run python tests/runtime/run_runtime_validation.py --tier fast --fixture all
```

### Runtime

Run runtime-capable validation against the pinned baseline checkout. This now performs full E2E execution by default:

```bash
uv run python tests/runtime/run_runtime_validation.py --tier runtime --fixture upscale-model-loader
```

Run both official runtime fixtures:

```bash
uv run python tests/runtime/run_runtime_validation.py --tier runtime --fixture all
```

### Model Provisioning

If a runtime fixture is missing required models, the harness will report `model provisioning failure`.

To print the required download commands without executing them:

```bash
uv run python tests/runtime/run_runtime_validation.py --tier runtime --fixture all --print-download-plan
```

Model downloads should be approval-gated and should target the existing `/home/peyton/code/ComfyUI/models/...` directories.

## Failure Classification

The runtime harness classifies failures as:

- `repo regression`
- `model provisioning failure`
- `fixture bug`
- `environment/setup failure`

This classification matters more than raw pass/fail. A failed run without classification is not actionable enough for maintenance work.

## Notes

- `unsafe-kwargs` and `subgraph-identifiers` are committed fast-tier regression fixtures. They are not runtime-tier fixtures.
- `upscale-model-loader` and `text-to-image` are the current runtime-tier fixtures and are based on official ComfyUI tutorials.
- Runtime-tier success now means:
  - generated Python parses
  - generated script executes
  - a new output file is created
  - output dimensions meet expectations
  - output metadata contains expected markers
- `Save As Script` route validation is still phase 2 work.
