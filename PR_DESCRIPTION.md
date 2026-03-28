## Summary

This PR adds a runtime validation path for exported workflows so exporter changes can be checked at two levels:

- fast exporter-only validation
- runtime validation against a pinned local ComfyUI checkout

It includes committed fixtures for:
- `upscale-model-loader`
- `text-to-image`
- `unsafe-kwargs`
- `subgraph-identifiers`

It also updates the exporter so generated scripts preserve workflow metadata and hidden runtime inputs needed for end-to-end execution.

## Included

- runtime validation harness in `tests/runtime/run_runtime_validation.py`
- runtime fixtures in `tests/fixtures/runtime/`
- exporter support changes in `comfyui_to_python.py`

## Validation

Planned validation commands:

```bash
uv run python tests/runtime/run_runtime_validation.py --tier fast --fixture all
uv run python tests/runtime/run_runtime_validation.py --tier runtime --fixture all
```

Runtime-tier failures are classified as:
- `repo regression`
- `model provisioning failure`
- `fixture bug`
- `environment/setup failure`
