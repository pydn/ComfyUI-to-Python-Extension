import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tomllib
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "integration_tests" / "environment.toml"
LOCK_PATH = ROOT / "integration_tests" / "environment.lock.json"


@dataclass
class RepoSpec:
    name: str
    repo: str
    ref: str
    path: Path
    tier: int = 1
    requirements: list[str] | None = None
    python_packages: list[str] | None = None


@dataclass
class AssetSpec:
    name: str
    kind: str
    path: Path
    tier: int = 1
    url: str | None = None
    sha256: str | None = None


@dataclass
class LocalExtensionSpec:
    source: Path
    path: Path


def load_manifest() -> dict[str, Any]:
    return tomllib.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def run_command(args: list[str], *, cwd: Path | None = None) -> str:
    completed = subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return completed.stdout.strip()


def run_uv_pip_install(args: list[str], *, cwd: Path | None = None) -> str:
    return run_command(["uv", "pip", "install", *args], cwd=cwd)


def ensure_repo(spec: RepoSpec) -> dict[str, Any]:
    spec.path.parent.mkdir(parents=True, exist_ok=True)
    if not spec.path.exists():
        run_command(["git", "clone", spec.repo, str(spec.path)])
    run_command(["git", "fetch", "--all", "--tags"], cwd=spec.path)
    run_command(["git", "checkout", spec.ref], cwd=spec.path)
    try:
        run_command(["git", "pull", "--ff-only"], cwd=spec.path)
    except subprocess.CalledProcessError:
        pass
    commit = run_command(["git", "rev-parse", "HEAD"], cwd=spec.path)
    installed_requirements: list[str] = []
    for requirement in spec.requirements or []:
        requirement_path = spec.path / requirement
        run_uv_pip_install(["-r", str(requirement_path)], cwd=ROOT)
        installed_requirements.append(str(requirement_path))

    installed_packages: list[str] = []
    if spec.python_packages:
        run_uv_pip_install(spec.python_packages, cwd=ROOT)
        installed_packages.extend(spec.python_packages)

    return {
        "name": spec.name,
        "repo": spec.repo,
        "ref": spec.ref,
        "path": str(spec.path),
        "commit": commit,
        "requirements": installed_requirements,
        "python_packages": installed_packages,
    }


def sha256_for(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def ensure_asset(spec: AssetSpec) -> dict[str, Any]:
    spec.path.parent.mkdir(parents=True, exist_ok=True)
    if spec.kind != "url" or not spec.url:
        raise ValueError(f"Unsupported asset spec: {spec}")
    if not spec.path.exists():
        with urllib.request.urlopen(spec.url, timeout=60) as response:
            spec.path.write_bytes(response.read())

    checksum = sha256_for(spec.path)
    if spec.sha256 and checksum != spec.sha256:
        raise ValueError(
            f"Checksum mismatch for {spec.name}: expected {spec.sha256}, got {checksum}"
        )
    return {
        "name": spec.name,
        "path": str(spec.path),
        "kind": spec.kind,
        "url": spec.url,
        "sha256": checksum,
        "size": spec.path.stat().st_size,
    }


def ensure_local_extension(spec: LocalExtensionSpec) -> dict[str, Any]:
    spec.path.parent.mkdir(parents=True, exist_ok=True)
    if spec.path.exists() or spec.path.is_symlink():
        if spec.path.is_symlink() and spec.path.resolve() == spec.source.resolve():
            return {
                "source": str(spec.source),
                "path": str(spec.path),
                "mode": "symlink",
            }
        if spec.path.is_dir():
            shutil.rmtree(spec.path)
        else:
            spec.path.unlink()
    spec.path.symlink_to(spec.source.resolve(), target_is_directory=True)
    return {
        "source": str(spec.source),
        "path": str(spec.path),
        "mode": "symlink",
    }


def parse_specs(
    manifest: dict[str, Any], *, tier: int
) -> tuple[Path, Path, RepoSpec, LocalExtensionSpec | None, list[RepoSpec], list[AssetSpec]]:
    workspace_root = ROOT / manifest["workspace"]["root"]
    cache_root = ROOT / manifest["workspace"]["cache"]
    comfyui_path = workspace_root / manifest["comfyui"]["path"]
    comfyui = RepoSpec(
        name="comfyui",
        repo=manifest["comfyui"]["repo"],
        ref=manifest["comfyui"]["ref"],
        path=comfyui_path,
        tier=1,
    )
    local_extension = None
    if "local_extension" in manifest:
        local_extension = LocalExtensionSpec(
            source=(ROOT / manifest["local_extension"]["source"]).resolve(),
            path=comfyui_path / manifest["local_extension"]["path"],
        )

    custom_nodes = []
    for entry in manifest.get("custom_nodes", []):
        if entry.get("tier", 1) > tier:
            continue
        custom_nodes.append(
            RepoSpec(
                name=entry["name"],
                repo=entry["repo"],
                ref=entry["ref"],
                path=comfyui_path / entry["path"],
                tier=entry.get("tier", 1),
                requirements=entry.get("requirements"),
                python_packages=entry.get("python_packages"),
            )
        )

    assets = []
    for entry in manifest.get("assets", []):
        if entry.get("tier", 1) > tier:
            continue
        assets.append(
            AssetSpec(
                name=entry["name"],
                kind=entry["kind"],
                url=entry.get("url"),
                sha256=entry.get("sha256"),
                path=comfyui_path / entry["path"],
                tier=entry.get("tier", 1),
            )
        )

    return workspace_root, cache_root, comfyui, local_extension, custom_nodes, assets


def write_lock(data: dict[str, Any]) -> None:
    LOCK_PATH.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def bootstrap(*, tier: int, clean: bool) -> Path:
    manifest = load_manifest()
    workspace_root, cache_root, comfyui, local_extension, custom_nodes, assets = parse_specs(
        manifest,
        tier=tier,
    )
    workspace_root.mkdir(parents=True, exist_ok=True)
    cache_root.mkdir(parents=True, exist_ok=True)

    if clean and workspace_root.exists():
        shutil.rmtree(workspace_root)
        workspace_root.mkdir(parents=True, exist_ok=True)

    comfyui_lock = ensure_repo(comfyui)
    local_extension_lock = (
        ensure_local_extension(local_extension) if local_extension is not None else None
    )
    custom_node_locks = [ensure_repo(spec) for spec in custom_nodes]
    asset_locks = [ensure_asset(spec) for spec in assets]

    lock_data = {
        "workspace_root": str(workspace_root),
        "cache_root": str(cache_root),
        "tier": tier,
        "comfyui": comfyui_lock,
        "local_extension": local_extension_lock,
        "custom_nodes": custom_node_locks,
        "assets": asset_locks,
    }
    write_lock(lock_data)
    return comfyui.path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bootstrap a reusable ComfyUI integration test environment."
    )
    parser.add_argument(
        "--tier",
        type=int,
        default=1,
        help="Bootstrap dependencies up to this tier. Defaults to 1.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove the existing integration workspace before bootstrapping.",
    )
    args = parser.parse_args()

    comfyui_path = bootstrap(tier=args.tier, clean=args.clean)
    print(f"Bootstrapped integration environment at {comfyui_path}")
    print(f"Wrote lock file to {LOCK_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
