# Runtime Validation Implementation Spec

## Document Status

- Date: March 28, 2026
- Scope: implementation spec only
- Approval status: approved for spec creation, not yet approved for implementation

## Problem

The repo now has a runtime validation strategy, but not an implementation contract. Runtime-sensitive changes still rely too heavily on ad hoc local setups and narrow regression tests. The repo needs a small, repeatable runtime validation harness that agents and maintainers can run consistently.

## Intent

Implement a phase-based runtime validation harness and add a project-scoped `runtime-e2e-agent` that can operate against it.

## Locked Decisions

- Baseline pinned ComfyUI checkout: `/home/peyton/code/ComfyUI`
- Runtime workflow fixtures will be committed in this repo
- Implementation covers both CLI/runtime and `Save As Script`, but in phases
- Phase 1: CLI/runtime first
- Phase 2: `Save As Script` route validation

## Goals

- create a repeatable runtime validation harness
- keep the harness small enough to maintain manually
- make the workflow corpus reviewable and committed in-repo
- support pinned-runtime validation with a stable command surface
- give the future `runtime-e2e-agent` a stable command surface

## Non-Goals

- no full browser automation in phase 1
- no image-quality regression testing
- no external CI/CD setup in this phase
- no vendoring of the ComfyUI repo into this repo
- no attempt to validate every possible custom-node workflow

## Phase Plan

### Phase 1: CLI / Runtime Harness

Phase 1 must provide:

- in-repo runtime workflow fixtures
- a command path that exports workflow JSON to Python
- a command path that validates generated Python parses
- a command path that executes generated Python against a pinned ComfyUI runtime
- clear pass/fail classification

This phase should be enough to validate:

- runtime/bootstrap regressions like `#143`
- generated-code validity issues when they must be checked against a real runtime
- runtime/bootstrap changes that affect node-loading or script execution

### Phase 2: `Save As Script` Route Validation

Phase 2 must build on the phase 1 harness and add:

- route-level validation of the `Save As Script` request path
- coverage for server-side export behavior in [__init__.py](/home/peyton/code/ComfyUI-to-Python-Extension/__init__.py)
- coverage for the exported payload shape expected by the frontend flow

Phase 2 should not start with full browser automation unless route-level checks prove insufficient.

## Directory Layout

The first implementation should add:

- `tests/fixtures/runtime/`
- `tests/fixtures/runtime/upscale-model-loader.json`
- `tests/fixtures/runtime/unsafe-kwargs.json`
- `tests/fixtures/runtime/subgraph-identifiers.json`
- `tests/runtime/`
- a focused runtime validation runner or helper module inside `tests/runtime/`
- `.codex/agents/runtime-e2e-agent.toml`

Optional supporting docs:

- `docs/runtime-validation.md`

## Fixture Rules

- prefer real ComfyUI workflow shapes over synthetic-only fixtures
- keep fixtures as small as possible while still reproducing the target behavior
- name fixtures after behavior, not issue numbers, when practical
- commit fixtures to the repo so they are reviewable and stable

## Initial Fixture Set

### `upscale-model-loader.json`

Purpose:

- validate the `#143`/`#148` runtime/bootstrap path

Assertions:

- export succeeds
- generated Python parses
- generated script reaches the relevant loader and upscale path without the old missing-node failure

### `unsafe-kwargs.json`

Purpose:

- validate mixed safe and unsafe keys in a real workflow shape

Assertions:

- export succeeds
- generated Python parses
- generated code remains safe when real workflow data contains symbol-heavy or invalid keys

### `subgraph-identifiers.json`

Purpose:

- validate that subgraph-expanded identifiers do not break generated Python in real workflow shapes

Assertions:

- export succeeds
- generated Python parses
- generated variable names are safe enough for execution

## Command Contract

The harness should expose two stable command categories.

### `fast`

Purpose:

- exporter-only validation without a real ComfyUI runtime

Examples:

- `uv run python -m unittest tests.test_upscale_model_loader_export -v`
- additional focused exporter tests as they are added

### `runtime`

Purpose:

- run runtime validation against the pinned baseline ComfyUI checkout

Environment:

- `COMFYUI_PATH=/home/peyton/code/ComfyUI`

Behavior:

- export fixture workflow to Python
- parse or compile generated Python
- execute generated Python with the pinned runtime available

## Runner Shape

The implementation should prefer one small runner over many scattered commands.

Recommended shape:

- a small Python entry point that:
  - selects a tier
  - selects a fixture or fixture subset
  - sets or reads `COMFYUI_PATH`
  - runs export
  - validates generated Python
  - optionally executes the generated script
  - reports failure classification

The runner must stay small and repo-local. It should not introduce a large new framework.

## Failure Classification Contract

Every runtime validation result must classify failure as one of:

- repo regression
- fixture bug
- environment/setup failure

This classification is mandatory in both manual runs and future agent reports.

## Runtime-E2E Agent Addition

A future implementation step should add:

- `.codex/agents/runtime-e2e-agent.toml`

Its instructions should align with:

- [runtime-e2e-agent-spec.md](/home/peyton/code/ComfyUI-to-Python-Extension/docs/specs/runtime-e2e-agent-spec.md)
- [runtime-validation-environment-spec.md](/home/peyton/code/ComfyUI-to-Python-Extension/docs/specs/runtime-validation-environment-spec.md)

The agent should:

- run the `runtime` tier
- report concise results
- avoid long logs
- return `pass`, `pass with risk`, or `fail`

## Validation Expectations

Phase 1 success means:

- the pinned runtime can validate at least the three initial fixtures
- the runner can distinguish export failures from runtime execution failures
- the runtime harness can be invoked consistently by maintainers and agents

Phase 2 success means:

- route-level `Save As Script` validation exists
- frontend/server export behavior can be checked without relying on a full browser automation stack

## Risks

- fixture maintenance can drift if fixtures are too complex
- local ComfyUI checkout state can become stale if not periodically refreshed intentionally
- runtime validation may still fail for environment reasons if `torch` or ComfyUI dependencies are missing

## Acceptance Criteria

- the implementation plan is explicit enough to build without inventing workflow shape later
- fixture names and locations are defined
- command tiers are defined
- phase split is defined
- failure classification is mandatory
- the `runtime-e2e-agent` rollout target is defined

## Next Step

If this implementation spec is approved, the next step is to produce a concrete implementation plan and then request explicit approval before creating:

- runtime fixture files
- the runner/helper module
- the `.codex/agents/runtime-e2e-agent.toml` file
- the short operator doc
