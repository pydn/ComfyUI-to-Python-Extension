# Integration Tests

This harness runs issue-cluster scenarios against a real ComfyUI checkout.
The environment is provisioned from `integration_tests/environment.toml` by
`integration_tests/bootstrap_env.py`, which clones ComfyUI, installs pinned
custom-node repos into `custom_nodes/`, installs any declared custom-node
Python requirements with `uv`, downloads declared assets, and writes a lock
file to `integration_tests/environment.lock.json`.

## What it covers

- Tier 1 baseline export with built-in nodes
- Tier 1 HTTP `/api/saveasscript` and `/saveasscript` route coverage
- Tier 1 core upscale export
- Tier 1 known-failure scenarios for invalid custom-node input names
- Tier 1 Windows-style path portability fixture

The scenario matrix lives in `integration_tests/scenarios.json`.

## Requirements

- Install this repo with the integration extra:

```bash
uv sync --extra integration
```

- The `integration` extra installs this repo's local integration harness dependencies.
- ComfyUI itself is provisioned by `integration_tests/bootstrap_env.py`, because the upstream repo is not currently consumable as a normal wheel build in this workflow.
- This extension available to the Python interpreter running the tests
- Optional: a running ComfyUI server for HTTP scenarios
- Optional custom node packs for issue-specific scenarios:
  - `rgthree-comfy`
  - `ComfyUI-Easy-Use`
  - `ComfyUI-Impact-Pack`

## Usage

Bootstrap the reusable environment:

```bash
uv run python integration_tests/bootstrap_env.py --tier 1
```

Install the bootstrapped ComfyUI runtime requirements into the current `uv` environment:

```bash
uv pip install -r .integration-env/ComfyUI/requirements.txt
```

If `integration_tests/environment.toml` declares repo-local custom-node
requirements or Python packages, rerun the bootstrap after updating the
manifest so those dependencies are installed into the current `uv` environment
as part of setup.

Run export scenarios only:

```bash
COMFYUI_PATH=.integration-env/ComfyUI \
uv run python integration_tests/run_against_comfyui.py
```

Run a specific scenario:

```bash
COMFYUI_PATH=.integration-env/ComfyUI \
uv run python integration_tests/run_against_comfyui.py --scenario core_upscale_export
```

Run HTTP scenarios against a running server:

```bash
COMFYUI_PATH=.integration-env/ComfyUI \
COMFYUI_BASE_URL=http://127.0.0.1:8188 \
uv run python integration_tests/run_against_comfyui.py --scenario baseline_http_export
```

## Result semantics

- `PASS`: scenario behaved as expected
- `SKIP`: missing fixture, server, or required custom node pack
- `XFAIL`: scenario is a known open issue and still fails as expected
- `UNEXPECTED-PASS`: a scenario marked as known failure now passes and should be reclassified
- `FAIL`: scenario regressed or the fixture is no longer valid

## Next fixture work

The current matrix is enough to start running real integration checks, but several high-value issue reproductions still need frozen workflow attachments from the issue tracker:

- nested subgraph parser repros
- CogVideoX missing-dependency repros
- runtime parity and metadata fixtures
- Desktop-specific menu-action smoke tests
- heavyweight runtime model assets for end-to-end image generation
