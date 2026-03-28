# Runtime Validation Environment Spec

## Purpose

Define the environment, fixture layout, and execution contract for end-to-end runtime validation of `ComfyUI-to-Python-Extension`.

## Problem

Exporter-only regression tests are necessary but insufficient for runtime/bootstrap-sensitive changes. Local verification becomes unreliable when tests depend on an arbitrary ComfyUI installation or on environment details that are not controlled. The repo needs a repeatable runtime validation harness.

## Goal

Create a stable runtime validation setup that:

- uses a pinned ComfyUI checkout
- validates generated scripts against a real runtime
- uses a small set of representative workflow fixtures
- clearly separates repo regressions from environment problems

## Non-Goals

- no image-quality benchmarking
- no full browser automation in the first phase
- no external CI/CD setup in this phase
- no attempt to cover every ComfyUI node or workflow shape

## Validation Model

### Tier 1: `fast`

Purpose:

- run quickly during local development
- validate exporter behavior without requiring a real ComfyUI runtime

Typical checks:

- focused unit or regression tests with injected mappings
- generated Python parse checks
- syntax compilation

### Tier 2: `runtime`

Purpose:

- validate generated scripts against a real pinned ComfyUI runtime

Typical checks:

- export from API-format workflow to Python
- parse/import generated Python
- execute generated script through the targeted runtime path
- confirm expected bootstrap and node-loading behavior

## Environment Requirements

- a local ComfyUI checkout available through a documented path convention
- the ability to point this repo to that checkout, preferably with `COMFYUI_PATH`
- required runtime dependencies installed in the validation environment, including `torch`
- all repo command execution through `uv`

## Proposed Path Convention

The validation harness should assume:

- this repo remains where it is
- the pinned ComfyUI checkout lives at a maintainer-chosen local path
- the runtime command surface uses `COMFYUI_PATH=/path/to/ComfyUI`

The exact checkout location does not need to be committed into this repo, but the contract for supplying it must be documented and stable.

## Workflow Fixture Corpus

The first committed or documented fixture set should cover:

- `upscale-model-loader`
  for `#143`-style runtime/bootstrap validation
- `unsafe-kwargs`
  for `#119` / `#96`-style generated-call validation against real workflows
- `subgraph-identifiers`
  for `#128`-style identifier safety

Fixture principles:

- prefer real workflow shapes from official ComfyUI examples when possible
- keep fixtures minimal but representative
- name fixtures after behavior, not issue numbers, when practical

## Assertions

The first phase should assert:

- export succeeds
- generated Python parses
- generated script can execute far enough to validate the targeted runtime path
- expected code patterns are present or absent when relevant

The first phase should not require:

- image-diff assertions
- performance benchmarking beyond obvious bootstrap regressions
- full frontend automation

## Failure Classification

Every runtime validation failure should be classified as one of:

- repo regression
- fixture bug
- environment/setup failure

This classification is mandatory because raw pass/fail is not enough for a maintenance workflow.

## Likely Future Deliverables

When implementation is approved, the runtime validation system will likely need:

- a fixtures directory for runtime workflows
- a short operator document for setting `COMFYUI_PATH`
- one or more helper commands or scripts for running:
  - `fast`
  - `runtime`
- a `runtime-e2e-agent` config file under `.codex/agents/`

## Acceptance Criteria

- runtime validation is defined around a pinned ComfyUI target
- the initial workflow corpus covers the main known runtime-sensitive issue classes
- validation tiers are clearly separated
- pass/fail reporting includes failure classification
- the setup is small enough to maintain manually inside Codex/chat workflows

## Open Questions

- should the workflow corpus be committed into this repo or referenced from a local external fixture path?
- should the first implementation cover only CLI/runtime execution, or also a later `Save As Script` route check?
