#!/usr/bin/env python3
"""Discover Skills and maintain Darwin's protected registry."""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adapters.codex import CodexAdapter, classify_location
from darwin_core.frontmatter import FrontmatterResult, parse_frontmatter_file
from telemetry import atomic_write_json, initialize_data_dir, load_json, resolve_data_dir, utc_now


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_fingerprint(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    complete = True
    symlink_detected = False
    for item in sorted(path.rglob("*"), key=lambda value: value.as_posix().lower()):
        relative = item.relative_to(path).as_posix()
        if any(part in {"__pycache__", ".git"} for part in Path(relative).parts):
            continue
        if item.is_symlink():
            symlink_detected = True
            try:
                target = os.readlink(item)
            except OSError:
                complete = False
                target = "<unreadable>"
            digest.update(b"L\0")
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update(target.encode("utf-8", errors="surrogateescape"))
            digest.update(b"\0")
            continue
        if item.is_dir():
            digest.update(b"D\0")
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            continue
        if not item.is_file():
            complete = False
            continue
        digest.update(b"F\0")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        try:
            digest.update(bytes.fromhex(sha256_file(item)))
        except OSError:
            complete = False
            digest.update(b"<unreadable>")
        digest.update(b"\0")
    return {
        "tree_sha256": digest.hexdigest(),
        "tree_hash_complete": complete,
        "symlink_detected": symlink_detected,
    }


def tree_sha256(path: Path) -> str:
    return str(tree_fingerprint(path)["tree_sha256"])


def parse_frontmatter(path: Path) -> FrontmatterResult:
    return parse_frontmatter_file(path)


def path_contains(path: Path, token: str) -> bool:
    return token.lower() in {part.lower() for part in path.parts}


def classify_skill(
    path: Path,
    discovery_root: Path,
    *,
    home: Path | None = None,
    cwd: Path | None = None,
) -> dict[str, object]:
    return classify_location(
        path,
        discovery_root,
        home=(home or Path.home()).expanduser(),
        cwd=(cwd or Path.cwd()).resolve(),
    )


def _runtime_targets(record: dict[str, Any]) -> tuple[str, ...]:
    values = record.get("runtime_targets")
    if isinstance(values, list) and all(isinstance(value, str) for value in values):
        return tuple(sorted(set(values)))
    runtime_id = record.get("runtime_id")
    return (str(runtime_id),) if runtime_id else ()


def set_runtime_dependency(record: dict[str, Any], status: str) -> None:
    normalized = status.replace("-", "_").upper()
    if normalized not in {"UNKNOWN", "REQUIRED", "NOT_REQUIRED"}:
        raise ValueError(f"Unsupported runtime dependency status: {status}")
    record["runtime_dependency_status"] = normalized
    record["runtime_dependency_updated_at"] = utc_now()
    for key in (
        "runtime_dependency_tree_sha256",
        "runtime_dependency_runtime_id",
        "runtime_dependency_deployment_id",
        "runtime_dependency_targets",
    ):
        record.pop(key, None)
    if normalized == "NOT_REQUIRED":
        record["runtime_dependency_tree_sha256"] = record.get("tree_sha256")
        record["runtime_dependency_runtime_id"] = record.get("runtime_id")
        record["runtime_dependency_deployment_id"] = record.get("deployment_id")
        record["runtime_dependency_targets"] = list(_runtime_targets(record))


def runtime_release_matches(record: dict[str, Any]) -> bool:
    return bool(
        record.get("runtime_dependency_status") == "NOT_REQUIRED"
        and record.get("runtime_dependency_tree_sha256") == record.get("tree_sha256")
        and record.get("runtime_dependency_runtime_id") == record.get("runtime_id")
        and record.get("runtime_dependency_deployment_id") == record.get("deployment_id")
        and tuple(record.get("runtime_dependency_targets") or ()) == _runtime_targets(record)
    )


def discover_roots(
    cwd: Path, explicit: list[str], include_plugin_cache: bool, home: Path | None = None
) -> list[Path]:
    adapter = CodexAdapter(home=home, cwd=cwd, include_plugin_cache=include_plugin_cache)
    candidates = [*adapter.discovery_roots(), *(Path(value).expanduser() for value in explicit)]
    seen: set[str] = set()
    roots: list[Path] = []
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        key = os.path.normcase(str(resolved))
        if key not in seen and resolved.is_dir():
            seen.add(key)
            roots.append(resolved)
    return roots
def build_record(
    skill_md: Path,
    previous: dict[str, Any] | None = None,
    *,
    discovery_root: Path | None = None,
    home: Path | None = None,
    cwd: Path | None = None,
) -> dict[str, Any]:
    folder = skill_md.parent.resolve()
    root = (discovery_root or folder.parent).resolve()
    frontmatter = parse_frontmatter(skill_md)
    metadata = frontmatter.fields
    classification = classify_skill(folder, root, home=home, cwd=cwd)
    manageable = bool(classification["manageable"])
    declared_name = metadata.get("name") if isinstance(metadata.get("name"), str) else None
    name = declared_name or folder.name
    now = utc_now()
    fingerprint = tree_fingerprint(folder)
    record = {
        "record_id": hashlib.sha256(str(folder).encode("utf-8")).hexdigest()[:16],
        "skill_id": name,
        "display_name": name,
        "description": metadata.get("description", "") if isinstance(metadata.get("description"), str) else "",
        "path": str(folder),
        "skill_md": str(skill_md.resolve()),
        "origin": classification["origin"],
        "scope": classification["scope"],
        "runtime_id": classification["runtime_id"],
        "deployment_id": classification["deployment_id"],
        "runtime_targets": classification["runtime_targets"],
        "discovery_root": str(root),
        "asset_state": classification["asset_state"],
        "manageable": manageable and not folder.is_symlink(),
        "managed": False,
        "protected": not manageable,
        "protection_reason": classification["protection_reason"],
        "content_sha256": sha256_file(skill_md),
        **fingerprint,
        "first_seen_at": now,
        "last_seen_at": now,
        "status": "DISCOVERED",
        "runtime_dependency_status": "UNKNOWN",
        **{
            key: value
            for key, value in classification.items()
            if key.startswith("plugin_")
        },
        **frontmatter.as_record_fields(),
    }
    if previous:
        for key in (
            "first_seen_at",
            "managed",
            "status",
            "notes",
        ):
            if key in previous:
                record[key] = previous[key]
        previous_status = previous.get("runtime_dependency_status", "UNKNOWN")
        if previous_status != "NOT_REQUIRED":
            record["runtime_dependency_status"] = previous_status
        elif (
            previous.get("runtime_dependency_tree_sha256") == record["tree_sha256"]
            and previous.get("runtime_dependency_runtime_id") == record["runtime_id"]
            and previous.get("runtime_dependency_deployment_id") == record["deployment_id"]
            and tuple(previous.get("runtime_dependency_targets") or ()) == _runtime_targets(record)
        ):
            for key in (
                "runtime_dependency_status",
                "runtime_dependency_updated_at",
                "runtime_dependency_tree_sha256",
                "runtime_dependency_runtime_id",
                "runtime_dependency_deployment_id",
                "runtime_dependency_targets",
            ):
                if key in previous:
                    record[key] = previous[key]
    return record


def scan_registry(
    data_dir: Path,
    roots: list[Path],
    *,
    home: Path | None = None,
    cwd: Path | None = None,
) -> dict[str, Any]:
    registry_path = data_dir / "registry.json"
    previous = load_json(registry_path, {})
    previous_by_path = {
        os.path.normcase(str(item.get("path", ""))): item
        for item in previous.get("skills", [])
        if item.get("path")
    }
    records: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for root in roots:
        for skill_md in root.rglob("SKILL.md"):
            if not skill_md.is_file():
                continue
            folder_key = os.path.normcase(str(skill_md.parent.resolve()))
            if folder_key in seen_paths:
                continue
            seen_paths.add(folder_key)
            records.append(
                build_record(
                    skill_md,
                    previous_by_path.get(folder_key),
                    discovery_root=root,
                    home=home,
                    cwd=cwd,
                )
            )

    # An archived Skill is intentionally absent from its original scan root.
    # Preserve its registry record so a later scan cannot break restore.
    for item in previous.get("skills", []):
        if item.get("status") == "ARCHIVED":
            original_key = os.path.normcase(str(item.get("path", "")))
            if original_key not in seen_paths:
                records.append(item)

    runtime_name_counts = collections.Counter(
        (_runtime_targets(item), item.get("deployment_id"), item.get("skill_id"))
        for item in records
        if item.get("status") != "ARCHIVED"
    )
    for item in records:
        item["runtime_unique_copy"] = runtime_name_counts[
            (_runtime_targets(item), item.get("deployment_id"), item.get("skill_id"))
        ] == 1

    registry = {
        "schema_version": 1,
        "generated_at": utc_now(),
        "scan_roots": [str(root) for root in roots],
        "skills": sorted(records, key=lambda item: (item["skill_id"].lower(), item["path"].lower())),
    }
    atomic_write_json(registry_path, registry)
    return registry


def select_skill(registry: dict[str, Any], name: str, path: str | None = None) -> dict[str, Any]:
    matches = [item for item in registry.get("skills", []) if item.get("skill_id") == name]
    if path:
        target = os.path.normcase(str(Path(path).expanduser().resolve()))
        matches = [item for item in matches if os.path.normcase(item.get("path", "")) == target]
    if not matches:
        raise SystemExit(f"Skill not found in registry: {name}")
    if len(matches) > 1:
        raise SystemExit(f"Skill name is ambiguous; pass --path. Matches: {[item['path'] for item in matches]}")
    return matches[0]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Darwin Skill registry")
    parser.add_argument("--data-dir")
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan")
    scan.add_argument("--root", action="append", default=[], help="Additional Skill root")
    scan.add_argument("--include-plugin-cache", action="store_true")

    listing = sub.add_parser("list")
    listing.add_argument("--only", choices=("manageable", "protected", "managed", "all"), default="all")

    show = sub.add_parser("show")
    show.add_argument("--skill", required=True)
    show.add_argument("--path")

    manage = sub.add_parser("set-managed")
    manage.add_argument("--skill", required=True)
    manage.add_argument("--path")
    manage.add_argument("--value", choices=("true", "false"), required=True)

    dependency = sub.add_parser("set-runtime-dependency")
    dependency.add_argument("--skill", required=True)
    dependency.add_argument("--path")
    dependency.add_argument(
        "--status",
        choices=("required", "not-required", "unknown"),
        required=True,
    )
    return parser


def print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    data_dir = initialize_data_dir(resolve_data_dir(args.data_dir), write_locator=not bool(args.data_dir))
    registry_path = data_dir / "registry.json"

    if args.command == "scan":
        roots = discover_roots(Path.cwd(), args.root, args.include_plugin_cache)
        registry = scan_registry(data_dir, roots)
        active_assets = sum(
            1
            for item in registry["skills"]
            if item.get("asset_state") in {"ACTIVE_RUNTIME_ASSET", "ACTIVE_PLUGIN_ASSET"}
        )
        inactive_cache = sum(
            1 for item in registry["skills"] if item.get("asset_state") == "INACTIVE_CACHED_VERSION"
        )
        unknown_cache = sum(
            1 for item in registry["skills"] if item.get("asset_state") == "CACHED_VERSION_UNKNOWN"
        )
        print_json(
            {
                "data_dir": str(data_dir),
                "skills": len(registry["skills"]),
                "manageable": sum(1 for item in registry["skills"] if item["manageable"]),
                "protected": sum(1 for item in registry["skills"] if item["protected"]),
                "active_assets": active_assets,
                "inactive_cached_versions": inactive_cache,
                "unknown_cached_versions": unknown_cache,
                "roots": registry["scan_roots"],
                "limitations": [
                    "This scan is structural and does not prove historical usage.",
                    "Plugin cache scanning is opt-in to avoid a large duplicated inventory.",
                ],
            }
        )
        return 0

    registry = load_json(registry_path, None)
    if not registry:
        raise SystemExit("Registry is missing. Run registry.py scan first.")

    if args.command == "list":
        skills = registry.get("skills", [])
        if args.only != "all":
            key = args.only
            skills = [item for item in skills if bool(item.get(key))]
        print_json(skills)
        return 0

    selected = select_skill(registry, args.skill, getattr(args, "path", None))
    if args.command == "show":
        print_json(selected)
        return 0

    if args.command == "set-runtime-dependency":
        set_runtime_dependency(selected, args.status)
        atomic_write_json(registry_path, registry)
        print_json(selected)
        return 0

    value = args.value == "true"
    if value and not selected.get("manageable"):
        raise SystemExit("Protected or external Skills cannot be enrolled in Darwin v0.3.")
    selected["managed"] = value
    selected["managed_updated_at"] = utc_now()
    atomic_write_json(registry_path, registry)
    print_json(selected)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
