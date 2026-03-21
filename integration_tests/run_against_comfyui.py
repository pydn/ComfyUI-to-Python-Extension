import argparse
import ast
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from comfyui_to_python import ExportStageError, export_workflow, format_export_exception


SCENARIOS_PATH = ROOT / "integration_tests" / "scenarios.json"


@dataclass
class Scenario:
    id: str
    title: str
    kind: str
    workflow: str
    expected: str
    tier: int = 1
    covers: list[str] = field(default_factory=list)
    required_node_packs: list[str] = field(default_factory=list)
    required_assets: list[str] = field(default_factory=list)
    output_prefix: str | None = None

    @property
    def workflow_path(self) -> Path:
        return ROOT / self.workflow


@dataclass
class ScenarioResult:
    scenario: Scenario
    status: str
    detail: str


def load_scenarios() -> list[Scenario]:
    raw = json.loads(SCENARIOS_PATH.read_text(encoding="utf-8"))
    return [Scenario(**item) for item in raw]


def detect_custom_node_packs(comfyui_path: Path) -> set[str]:
    custom_nodes_dir = comfyui_path / "custom_nodes"
    if not custom_nodes_dir.exists():
        return set()

    installed = set()
    for child in custom_nodes_dir.iterdir():
        if not child.is_dir():
            continue
        name = child.name.lower()
        if "rgthree" in name:
            installed.add("rgthree")
        if "easy" in name and "use" in name:
            installed.add("easy-use")
        if "impact" in name:
            installed.add("impact-pack")
        if "cogvideo" in name:
            installed.add("cogvideox")
    return installed


def run_export_scenario(scenario: Scenario) -> ScenarioResult:
    workflow_text = scenario.workflow_path.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmp_dir:
        output_path = Path(tmp_dir) / f"{scenario.id}.py"
        try:
            result = export_workflow(
                workflow=workflow_text,
                output_file=str(output_path),
                queue_size=1,
                needs_init_custom_nodes=True,
            )
        except Exception as exc:
            payload = format_export_exception(exc)
            if scenario.expected == "known_failure" and is_expected_known_failure(payload):
                return ScenarioResult(
                    scenario=scenario,
                    status="xfail",
                    detail=json.dumps(payload, indent=2),
                )
            return ScenarioResult(
                scenario=scenario,
                status="fail",
                detail=json.dumps(payload, indent=2),
            )

        code = output_path.read_text(encoding="utf-8")
        ast.parse(code)
        if scenario.expected == "known_failure":
            return ScenarioResult(
                scenario=scenario,
                status="unexpected-pass",
                detail="Scenario is marked known_failure but export succeeded.",
            )
        return ScenarioResult(
            scenario=scenario,
            status="pass",
            detail=f"Generated {len(code.splitlines())} lines of Python.",
        )


def run_execution_scenario(scenario: Scenario, comfyui_path: Path) -> ScenarioResult:
    workflow_text = scenario.workflow_path.read_text(encoding="utf-8")
    output_prefix = scenario.output_prefix
    if not output_prefix:
        return ScenarioResult(
            scenario=scenario,
            status="fail",
            detail="Execution scenario is missing an output_prefix.",
        )

    output_dir = comfyui_path / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    before_files = {
        path.name
        for path in output_dir.glob(f"{output_prefix}*")
        if path.is_file()
    }

    with tempfile.TemporaryDirectory() as tmp_dir:
        script_path = Path(tmp_dir) / f"{scenario.id}.py"
        try:
            export_workflow(
                workflow=workflow_text,
                output_file=str(script_path),
                queue_size=1,
                needs_init_custom_nodes=True,
            )
        except Exception as exc:
            payload = format_export_exception(exc)
            return ScenarioResult(
                scenario=scenario,
                status="fail",
                detail=f"Failed to export runtime script:\n{json.dumps(payload, indent=2)}",
            )

        env = os.environ.copy()
        env["COMFYUI_PATH"] = str(comfyui_path)
        completed = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=180,
        )

    if completed.returncode != 0:
        detail = "\n".join(
            part
            for part in (
                f"Generated script exited with code {completed.returncode}.",
                f"stdout:\n{completed.stdout.strip()}" if completed.stdout.strip() else "",
                f"stderr:\n{completed.stderr.strip()}" if completed.stderr.strip() else "",
            )
            if part
        )
        return ScenarioResult(scenario=scenario, status="fail", detail=detail)

    after_files = {
        path.name
        for path in output_dir.glob(f"{output_prefix}*")
        if path.is_file()
    }
    new_files = sorted(after_files - before_files)
    if not new_files:
        detail = "\n".join(
            part
            for part in (
                f"Generated script completed but no new output files matched prefix {output_prefix!r}.",
                f"stdout:\n{completed.stdout.strip()}" if completed.stdout.strip() else "",
                f"stderr:\n{completed.stderr.strip()}" if completed.stderr.strip() else "",
            )
            if part
        )
        return ScenarioResult(scenario=scenario, status="fail", detail=detail)

    return ScenarioResult(
        scenario=scenario,
        status="pass",
        detail=f"Generated script created {len(new_files)} output file(s): {', '.join(new_files)}",
    )


def is_expected_known_failure(payload: dict[str, Any]) -> bool:
    error_text = " ".join(
        str(payload.get(key, ""))
        for key in ("error", "class_type", "stage")
    ).lower()
    known_patterns = (
        "invalidinput",
        "cannot parse",
        "unsupported node class",
        "keyword",
        "power lora",
        "impactwildcard",
        "easy_anything",
    )
    environment_patterns = (
        "unable to initialize comfyui custom nodes",
        "modulenotfounderror",
        "no module named",
    )
    if any(pattern in error_text for pattern in environment_patterns):
        return False
    return any(pattern in error_text for pattern in known_patterns)


def post_json(base_url: str, path: str, payload: dict[str, Any]) -> urllib.request.addinfourl:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return urllib.request.urlopen(request, timeout=30)


def run_http_scenario(scenario: Scenario, base_url: str) -> ScenarioResult:
    workflow_text = scenario.workflow_path.read_text(encoding="utf-8")
    payload = {
        "name": f"{scenario.id}.json",
        "workflow": workflow_text,
    }
    last_error = None
    for path in ("/api/saveasscript", "/saveasscript"):
        try:
            with post_json(base_url, path, payload) as response:
                body = response.read().decode("utf-8")
                if response.status == 200:
                    ast.parse(body)
                    return ScenarioResult(
                        scenario=scenario,
                        status="pass",
                        detail=f"HTTP export succeeded via {path}.",
                    )
                last_error = f"{path}: HTTP {response.status}"
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8")
            last_error = f"{path}: HTTP {exc.code} {body}"
        except urllib.error.URLError as exc:
            last_error = f"{path}: {exc}"
            break

    return ScenarioResult(
        scenario=scenario,
        status="fail",
        detail=last_error or "HTTP route failed.",
    )


def run_scenarios(
    scenarios: list[Scenario],
    *,
    comfyui_path: Path,
    base_url: str | None,
) -> list[ScenarioResult]:
    os.environ["COMFYUI_PATH"] = str(comfyui_path)
    installed_packs = detect_custom_node_packs(comfyui_path)
    results: list[ScenarioResult] = []

    for scenario in scenarios:
        if not scenario.workflow_path.exists():
            results.append(
                ScenarioResult(
                    scenario=scenario,
                    status="skip",
                    detail=f"Missing workflow fixture: {scenario.workflow_path}",
                )
            )
            continue

        missing_packs = [
            pack for pack in scenario.required_node_packs if pack not in installed_packs
        ]
        if missing_packs:
            results.append(
                ScenarioResult(
                    scenario=scenario,
                    status="skip",
                    detail=f"Missing custom node packs: {', '.join(missing_packs)}",
                )
            )
            continue

        missing_assets = [
            asset for asset in scenario.required_assets if not (comfyui_path / asset).exists()
        ]
        if missing_assets:
            results.append(
                ScenarioResult(
                    scenario=scenario,
                    status="skip",
                    detail=f"Missing required assets: {', '.join(missing_assets)}",
                )
            )
            continue

        if scenario.kind == "http":
            if not base_url:
                results.append(
                    ScenarioResult(
                        scenario=scenario,
                        status="skip",
                        detail="COMFYUI_BASE_URL not set for HTTP scenario.",
                    )
                )
                continue
            results.append(run_http_scenario(scenario, base_url))
            continue
        if scenario.kind == "execution":
            results.append(run_execution_scenario(scenario, comfyui_path))
            continue

        results.append(run_export_scenario(scenario))

    return results


def print_results(results: list[ScenarioResult]) -> int:
    counts = {"pass": 0, "fail": 0, "skip": 0, "xfail": 0, "unexpected-pass": 0}
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1
        print(f"[{result.status.upper()}] {result.scenario.id}: {result.scenario.title}")
        print(f"  covers: {', '.join(result.scenario.covers) or 'n/a'}")
        print(f"  detail: {result.detail}")

    print("")
    print(
        "Summary: "
        + ", ".join(f"{status}={count}" for status, count in counts.items() if count)
    )
    return 1 if counts["fail"] or counts["unexpected-pass"] else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run fixture-driven integration scenarios against a real ComfyUI checkout."
    )
    parser.add_argument(
        "--scenario",
        action="append",
        help="Run only the named scenario id. Can be provided multiple times.",
    )
    parser.add_argument(
        "--tier",
        type=int,
        default=1,
        help="Run scenarios up to this tier number. Defaults to tier 1.",
    )
    parser.add_argument(
        "--comfyui-path",
        default=os.environ.get("COMFYUI_PATH", ""),
        help="Path to the target ComfyUI checkout. Defaults to COMFYUI_PATH.",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("COMFYUI_BASE_URL", ""),
        help="Optional running ComfyUI server base URL for HTTP scenarios.",
    )
    args = parser.parse_args()

    if not args.comfyui_path:
        print("Set COMFYUI_PATH or pass --comfyui-path to run integration scenarios.")
        return 2

    scenarios = load_scenarios()
    if args.scenario:
        requested = set(args.scenario)
        scenarios = [scenario for scenario in scenarios if scenario.id in requested]
    else:
        scenarios = [scenario for scenario in scenarios if scenario.tier <= args.tier]

    if not scenarios:
        print("No scenarios selected.")
        return 2

    results = run_scenarios(
        scenarios,
        comfyui_path=Path(args.comfyui_path).resolve(),
        base_url=args.base_url or None,
    )
    return print_results(results)


if __name__ == "__main__":
    raise SystemExit(main())
