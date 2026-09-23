#!/usr/bin/env python3
"""Two-step, reversible Skill archival. Permanent deletion is intentionally absent."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import shutil
import uuid
from typing import Any

from registry import runtime_release_matches, select_skill, tree_sha256
from telemetry import (
    atomic_write_json,
    initialize_data_dir,
    load_json,
    parse_time,
    record_event,
    resolve_data_dir,
    utc_now,
)


def is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def load_registry(data_dir: Path) -> dict[str, Any]:
    registry = load_json(data_dir / "registry.json", None)
    if not registry:
        raise SystemExit("Registry is missing. Run registry.py scan first.")
    return registry


def save_registry(data_dir: Path, registry: dict[str, Any]) -> None:
    atomic_write_json(data_dir / "registry.json", registry)


def ensure_archivable(
    skill: dict[str, Any],
    registry: dict[str, Any],
    *,
    require_runtime_release: bool = True,
) -> Path:
    if skill.get("protected") or not skill.get("manageable"):
        raise SystemExit("Protected or external Skills cannot be archived by Darwin v0.3.")
    if not skill.get("structural_valid", False):
        raise SystemExit("Structurally invalid Skills cannot receive an archive plan.")
    if not skill.get("tree_hash_complete", False):
        raise SystemExit("An incomplete tree fingerprint cannot receive an archive plan.")
    if require_runtime_release and not runtime_release_matches(skill):
        raise SystemExit(
            "Archive planning requires an explicit runtime dependency status of NOT_REQUIRED. "
            "Record it with registry.py set-runtime-dependency after confirming the target runtime no longer needs this copy."
        )
    source = Path(skill["path"])
    if not source.exists() or not source.is_dir():
        raise SystemExit(f"Skill directory does not exist: {source}")
    if source.is_symlink() or any(parent.is_symlink() for parent in source.parents if parent != parent.parent):
        raise SystemExit("Symlinked Skill paths are rejected to prevent escaping the approved root.")
    resolved = source.resolve()
    roots = [Path(value).resolve() for value in registry.get("scan_roots", []) if Path(value).exists()]
    if not any(is_within(resolved, root) for root in roots):
        raise SystemExit("Skill path is outside all scanned roots.")
    lower_parts = {part.lower() for part in resolved.parts}
    if ".system" in lower_parts or ("plugins" in lower_parts and "cache" in lower_parts):
        raise SystemExit("System and plugin-bundled paths are always protected.")
    if require_runtime_release and tree_sha256(resolved) != skill.get("tree_sha256"):
        raise SystemExit(
            "Skill content changed since the runtime dependency was released. "
            "Run registry.py scan and re-confirm the runtime dependency for the current content."
        )
    return resolved


def deployment_binding(skill: dict[str, Any]) -> dict[str, Any]:
    return {
        "runtime_id": skill.get("runtime_id"),
        "deployment_id": skill.get("deployment_id"),
        "runtime_targets": sorted(skill.get("runtime_targets") or []),
    }


def create_approval(data_dir: Path, value: dict[str, Any]) -> dict[str, Any]:
    now = dt.datetime.now(dt.timezone.utc)
    approval = {
        "schema_version": 1,
        "approval_id": str(uuid.uuid4()),
        "status": "PENDING",
        "created_at": now.isoformat().replace("+00:00", "Z"),
        "expires_at": (now + dt.timedelta(hours=24)).isoformat().replace("+00:00", "Z"),
        **value,
    }
    atomic_write_json(data_dir / "approvals" / f"{approval['approval_id']}.json", approval)
    return approval


def load_pending_approval(data_dir: Path, approval_id: str, action: str) -> tuple[Path, dict[str, Any]]:
    path = data_dir / "approvals" / f"{approval_id}.json"
    approval = load_json(path, None)
    if not approval:
        raise SystemExit("Approval record not found.")
    if approval.get("status") != "PENDING" or approval.get("action") != action:
        raise SystemExit("Approval is not pending for this action.")
    if parse_time(approval["expires_at"]) <= dt.datetime.now(dt.timezone.utc):
        approval["status"] = "EXPIRED"
        atomic_write_json(path, approval)
        raise SystemExit("Approval expired; create a new plan.")
    return path, approval


def load_index(data_dir: Path) -> dict[str, Any]:
    return load_json(data_dir / "archive-index.json", {"schema_version": 1, "archives": []})


def archive_plan(data_dir: Path, skill_name: str, skill_path: str | None) -> dict[str, Any]:
    registry = load_registry(data_dir)
    skill = select_skill(registry, skill_name, skill_path)
    source = ensure_archivable(skill, registry)
    archive_id = str(uuid.uuid4())
    destination = data_dir / "archive" / skill["record_id"] / archive_id
    phrase = f"APPROVE ARCHIVE {skill['skill_id']}"
    approval = create_approval(
        data_dir,
        {
            "action": "ARCHIVE",
            "archive_id": archive_id,
            "record_id": skill["record_id"],
            "skill_id": skill["skill_id"],
            "source_path": str(source),
            "destination_path": str(destination),
            "target_tree_sha256": tree_sha256(source),
            **deployment_binding(skill),
            "required_approval_text": phrase,
        },
    )
    record_event(
        data_dir,
        "archive_planned",
        {"skill_id": skill["skill_id"], "approval_id": approval["approval_id"], "outcome": "UNKNOWN"},
    )
    return {
        "approval_id": approval["approval_id"],
        "action": "ARCHIVE",
        "skill": {"name": skill["skill_id"], "description": skill.get("description", ""), "path": str(source)},
        **deployment_binding(skill),
        "destination": str(destination),
        "target_tree_sha256": approval["target_tree_sha256"],
        "rollback": "Use plan-restore and restore with a separate explicit approval.",
        "expires_at": approval["expires_at"],
        "required_user_reply": phrase,
        "warning": "Do not execute until the user personally returns the exact approval phrase.",
    }


def archive_execute(data_dir: Path, approval_id: str, approval_text: str) -> dict[str, Any]:
    approval_path, approval = load_pending_approval(data_dir, approval_id, "ARCHIVE")
    if approval_text != approval["required_approval_text"]:
        raise SystemExit("Approval text does not exactly match the plan.")
    registry = load_registry(data_dir)
    matches = [item for item in registry.get("skills", []) if item.get("record_id") == approval["record_id"]]
    if len(matches) != 1:
        raise SystemExit("Approved registry target no longer resolves uniquely.")
    skill = matches[0]
    source = ensure_archivable(skill, registry)
    if os.path.normcase(str(source)) != os.path.normcase(str(Path(approval["source_path"]).resolve())):
        raise SystemExit("Target path changed after approval.")
    binding = deployment_binding(skill)
    if any(approval.get(key) != value for key, value in binding.items()):
        raise SystemExit("Target runtime or deployment changed after approval; create a new plan.")
    if tree_sha256(source) != approval["target_tree_sha256"]:
        raise SystemExit("Target content changed after approval; create a new plan.")
    destination = Path(approval["destination_path"]).resolve()
    archive_root = (data_dir / "archive").resolve()
    if not is_within(destination, archive_root) or destination.exists():
        raise SystemExit("Archive destination is unsafe or already exists.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))

    archived_at = utc_now()
    index = load_index(data_dir)
    index["archives"].append(
        {
            "archive_id": approval["archive_id"],
            "record_id": skill["record_id"],
            "skill_id": skill["skill_id"],
            "description": skill.get("description", ""),
            "original_path": approval["source_path"],
            "archive_path": str(destination),
            "tree_sha256": approval["target_tree_sha256"],
            "archived_at": archived_at,
            "restored_at": None,
            "approval_id": approval_id,
            "user_approval_text": approval_text,
        }
    )
    atomic_write_json(data_dir / "archive-index.json", index)
    skill["status"] = "ARCHIVED"
    skill["archived_path"] = str(destination)
    skill["archived_at"] = archived_at
    save_registry(data_dir, registry)
    approval["status"] = "CONSUMED"
    approval["consumed_at"] = archived_at
    approval["user_approval_text"] = approval_text
    atomic_write_json(approval_path, approval)
    record_event(
        data_dir,
        "skill_archived",
        {"skill_id": skill["skill_id"], "archive_id": approval["archive_id"], "approval_id": approval_id},
    )
    return {"archived": True, "archive_id": approval["archive_id"], "archive_path": str(destination)}


def restore_plan(data_dir: Path, archive_id: str) -> dict[str, Any]:
    index = load_index(data_dir)
    matches = [item for item in index["archives"] if item["archive_id"] == archive_id and not item.get("restored_at")]
    if len(matches) != 1:
        raise SystemExit("Active archive not found.")
    item = matches[0]
    archive_path = Path(item["archive_path"]).resolve()
    if not archive_path.is_dir() or not is_within(archive_path, (data_dir / "archive").resolve()):
        raise SystemExit("Archive payload is missing or unsafe.")
    phrase = f"APPROVE RESTORE {archive_id}"
    approval = create_approval(
        data_dir,
        {
            "action": "RESTORE",
            "archive_id": archive_id,
            "record_id": item["record_id"],
            "skill_id": item["skill_id"],
            "source_path": str(archive_path),
            "destination_path": item["original_path"],
            "target_tree_sha256": item["tree_sha256"],
            "required_approval_text": phrase,
        },
    )
    return {
        "approval_id": approval["approval_id"],
        "action": "RESTORE",
        "archive_id": archive_id,
        "source": str(archive_path),
        "destination": item["original_path"],
        "target_tree_sha256": approval["target_tree_sha256"],
        "required_user_reply": phrase,
        "warning": "Do not execute until the user personally returns the exact approval phrase.",
    }


def restore_execute(data_dir: Path, approval_id: str, approval_text: str) -> dict[str, Any]:
    approval_path, approval = load_pending_approval(data_dir, approval_id, "RESTORE")
    if approval_text != approval["required_approval_text"]:
        raise SystemExit("Approval text does not exactly match the plan.")
    source = Path(approval["source_path"]).resolve()
    destination = Path(approval["destination_path"]).resolve()
    if not source.is_dir() or source.is_symlink() or not is_within(source, (data_dir / "archive").resolve()):
        raise SystemExit("Archive payload is missing or unsafe.")
    if destination.exists():
        raise SystemExit("Restore destination already exists.")
    registry = load_registry(data_dir)
    matches = [item for item in registry["skills"] if item.get("record_id") == approval["record_id"]]
    if len(matches) != 1 or matches[0].get("protected") or not matches[0].get("manageable"):
        raise SystemExit("Restore registry target is missing or protected.")
    roots = [Path(value).resolve() for value in registry.get("scan_roots", []) if Path(value).exists()]
    if not any(is_within(destination, root) for root in roots):
        raise SystemExit("Restore destination is outside all scanned roots.")
    lower_parts = {part.lower() for part in destination.parts}
    if ".system" in lower_parts or ("plugins" in lower_parts and "cache" in lower_parts):
        raise SystemExit("Restore destination is protected.")
    if tree_sha256(source) != approval["target_tree_sha256"]:
        raise SystemExit("Archive payload changed; restore aborted.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))

    restored_at = utc_now()
    index = load_index(data_dir)
    item = next(value for value in index["archives"] if value["archive_id"] == approval["archive_id"])
    item["restored_at"] = restored_at
    item["restore_approval_id"] = approval_id
    item["restore_user_approval_text"] = approval_text
    atomic_write_json(data_dir / "archive-index.json", index)

    skill = next(value for value in registry["skills"] if value["record_id"] == approval["record_id"])
    skill["status"] = "DISCOVERED"
    skill["path"] = str(destination)
    skill["skill_md"] = str(destination / "SKILL.md")
    skill.pop("archived_path", None)
    skill.pop("archived_at", None)
    save_registry(data_dir, registry)
    approval["status"] = "CONSUMED"
    approval["consumed_at"] = restored_at
    approval["user_approval_text"] = approval_text
    atomic_write_json(approval_path, approval)
    record_event(
        data_dir,
        "skill_restored",
        {"skill_id": skill["skill_id"], "archive_id": approval["archive_id"], "approval_id": approval_id},
    )
    return {"restored": True, "archive_id": approval["archive_id"], "path": str(destination)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Darwin reversible archive manager; no delete command exists")
    parser.add_argument("--data-dir")
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan")
    plan.add_argument("--skill", required=True)
    plan.add_argument("--path")

    execute = sub.add_parser("execute")
    execute.add_argument("--approval-id", required=True)
    execute.add_argument("--approval-text", required=True)

    sub.add_parser("list")

    plan_restore = sub.add_parser("plan-restore")
    plan_restore.add_argument("--archive-id", required=True)

    restore = sub.add_parser("restore")
    restore.add_argument("--approval-id", required=True)
    restore.add_argument("--approval-text", required=True)
    return parser


def print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    data_dir = initialize_data_dir(resolve_data_dir(args.data_dir), write_locator=not bool(args.data_dir))
    if args.command == "plan":
        print_json(archive_plan(data_dir, args.skill, args.path))
    elif args.command == "execute":
        print_json(archive_execute(data_dir, args.approval_id, args.approval_text))
    elif args.command == "list":
        print_json(load_index(data_dir))
    elif args.command == "plan-restore":
        print_json(restore_plan(data_dir, args.archive_id))
    elif args.command == "restore":
        print_json(restore_execute(data_dir, args.approval_id, args.approval_text))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
