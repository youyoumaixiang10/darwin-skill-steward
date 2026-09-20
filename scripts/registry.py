#!/usr/bin/env python3
"""Discover Skills and maintain Darwin's protected registry."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adapters.codex import CodexAdapter
from telemetry import atomic_write_json, initialize_data_dir, load_json, resolve_data_dir, utc_now


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(path.rglob("*"), key=lambda value: value.as_posix().lower()):
        if not item.is_file() or item.is_symlink():
            continue
        relative = item.relative_to(path).as_posix()
        if any(part in {"__pycache__", ".git"} for part in item.parts):
            continue
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(sha256_file(item)))
    return digest.hexdigest()


def parse_frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    result: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        match = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if match:
            value = match.group(2).strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
                value = value[1:-1]
            result[match.group(1)] = value
    return result


def path_contains(path: Path, token: str) -> bool:
    return token.lower() in {part.lower() for part in path.parts}


def classify_skill(path: Path) -> tuple[str, bool, str | None]:
    lower_parts = [part.lower() for part in path.parts]
    if ".system" in lower_parts:
        return "SYSTEM", False, "System Skill"
    if "plugins" in lower_parts and "cache" in lower_parts:
        official = any(part.startswith("openai-") for part in lower_parts)
        return (
            "OFFICIAL_PLUGIN" if official else "THIRD_PARTY_PLUGIN",
            False,
            "Plugin-bundled Skill",
        )
    if ".agents" in lower_parts:
        return "REPOSITORY", True, None
    return "USER", True, None


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
def build_record(skill_md: Path, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    folder = skill_md.parent.resolve()
    metadata = parse_frontmatter(skill_md)
    origin, manageable, reason = classify_skill(folder)
    name = metadata.get("name") or folder.name
    now = utc_now()
    record = {
        "record_id": hashlib.sha256(str(folder).encode("utf-8")).hexdigest()[:16],
        "skill_id": name,
        "description": metadata.get("description", ""),
        "path": str(folder),
        "skill_md": str(skill_md.resolve()),
        "origin": origin,
        "manageable": manageable and not folder.is_symlink(),
        "managed": False,
        "protected": not manageable,
        "protection_reason": reason,
        "content_sha256": sha256_file(skill_md),
        "tree_sha256": tree_sha256(folder),
        "first_seen_at": now,
        "last_seen_at": now,
        "status": "DISCOVERED",
    }
    if previous:
        for key in ("first_seen_at", "managed", "status", "notes"):
            if key in previous:
                record[key] = previous[key]
    return record


def scan_registry(data_dir: Path, roots: list[Path]) -> dict[str, Any]:
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
            records.append(build_record(skill_md, previous_by_path.get(folder_key)))

    # An archived Skill is intentionally absent from its original scan root.
    # Preserve its registry record so a later scan cannot break restore.
    for item in previous.get("skills", []):
        if item.get("status") == "ARCHIVED":
            original_key = os.path.normcase(str(item.get("path", "")))
            if original_key not in seen_paths:
                records.append(item)

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
        print_json(
            {
                "data_dir": str(data_dir),
                "skills": len(registry["skills"]),
                "manageable": sum(1 for item in registry["skills"] if item["manageable"]),
                "protected": sum(1 for item in registry["skills"] if item["protected"]),
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

    value = args.value == "true"
    if value and not selected.get("manageable"):
        raise SystemExit("Protected or external Skills cannot be enrolled in v0.1.")
    selected["managed"] = value
    selected["managed_updated_at"] = utc_now()
    atomic_write_json(registry_path, registry)
    print_json(selected)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
