#!/usr/bin/env python3
"""Operate Darwin runtime adapters from a small, auditable CLI."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from adapters import ClaudeCodeAdapter, ClaudeCoworkAdapter, CodexAdapter, DoubaoAdapter, WorkBuddyAdapter
from adapters._skill_package import file_sha256


def build_adapter(runtime: str, roots: list[str]):
    paths = [Path(value).expanduser().resolve() for value in roots]
    if runtime == "codex":
        return CodexAdapter()
    if runtime == "claude-code":
        return ClaudeCodeAdapter(roots=paths or None)
    if runtime == "claude-cowork":
        return ClaudeCoworkAdapter(roots=paths)
    if runtime == "workbuddy":
        return WorkBuddyAdapter(roots=paths or None)
    if runtime == "doubao":
        return DoubaoAdapter(roots=paths)
    raise ValueError(f"Unsupported runtime: {runtime}")


def find_asset(adapter, native_id: str):
    matches = [asset for asset in adapter.discover_assets() if asset.native_id == native_id]
    if not matches:
        raise ValueError(f"No asset named {native_id!r} was found for {adapter.runtime_id}")
    if len(matches) > 1:
        raise ValueError(f"Asset name {native_id!r} is ambiguous for {adapter.runtime_id}")
    return matches[0]


def command_list(args: argparse.Namespace) -> dict[str, object]:
    adapter = build_adapter(args.runtime, args.root)
    return {"runtime_id": adapter.runtime_id, "assets": [asdict(asset) for asset in adapter.discover_assets()]}


def command_package(args: argparse.Namespace) -> dict[str, object]:
    adapter = build_adapter(args.runtime, args.root)
    asset = find_asset(adapter, args.asset)
    artifact = adapter.package_candidate(asset, args.destination)
    if not isinstance(artifact, dict):
        raise ValueError(getattr(artifact, "reason", "Runtime cannot package this asset"))
    return {"asset": asdict(asset), "package": artifact}


def command_plan_apply(args: argparse.Namespace) -> dict[str, object]:
    adapter = build_adapter(args.runtime, args.root)
    asset = find_asset(adapter, args.asset)
    package_path = Path(args.package).expanduser().resolve()
    if not package_path.is_file():
        raise ValueError(f"Package does not exist: {package_path}")
    package = {
        "runtime_id": asset.runtime_id,
        "native_id": asset.native_id,
        "package_path": str(package_path),
        "sha256": file_sha256(package_path),
    }
    result = adapter.prepare_apply({"asset": asset, "package": package})
    if not isinstance(result, dict):
        raise ValueError(getattr(result, "reason", "Runtime cannot prepare an apply plan"))
    return result


def command_plan_rollback(args: argparse.Namespace) -> dict[str, object]:
    adapter = build_adapter(args.runtime, args.root)
    asset = find_asset(adapter, args.asset)
    package_path = Path(args.package).expanduser().resolve()
    if not package_path.is_file():
        raise ValueError(f"Package does not exist: {package_path}")
    package = {
        "runtime_id": asset.runtime_id,
        "native_id": asset.native_id,
        "package_path": str(package_path),
        "sha256": file_sha256(package_path),
    }
    result = adapter.prepare_rollback({"asset": asset, "package": package})
    if not isinstance(result, dict):
        raise ValueError(getattr(result, "reason", "Runtime cannot prepare a rollback plan"))
    return result


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Darwin cross-Agent runtime adapter CLI")
    result.add_argument("--runtime", required=True, choices=("codex", "claude-code", "claude-cowork", "workbuddy", "doubao"))
    result.add_argument("--root", action="append", default=[], help="Explicit exported or installed Skill root; repeat as needed")
    subparsers = result.add_subparsers(dest="command", required=True)
    list_parser = subparsers.add_parser("list")
    list_parser.set_defaults(handler=command_list)
    package_parser = subparsers.add_parser("package")
    package_parser.add_argument("--asset", required=True)
    package_parser.add_argument("--destination", required=True)
    package_parser.set_defaults(handler=command_package)
    plan_parser = subparsers.add_parser("plan-apply")
    plan_parser.add_argument("--asset", required=True)
    plan_parser.add_argument("--package", required=True)
    plan_parser.set_defaults(handler=command_plan_apply)
    rollback_parser = subparsers.add_parser("plan-rollback")
    rollback_parser.add_argument("--asset", required=True)
    rollback_parser.add_argument("--package", required=True)
    rollback_parser.set_defaults(handler=command_plan_rollback)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        result = args.handler(args)
    except (OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
