#!/usr/bin/env python3
"""Isolated, evidence-gated, human-approved Skill evolution."""

from __future__ import annotations

import argparse
import difflib
import json
import os
from pathlib import Path
import shutil
import sys
import uuid
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from darwin_core.evolution import promotion_gate as core_promotion_gate

from archive import (
    create_approval,
    ensure_archivable,
    load_pending_approval,
    load_registry,
    save_registry,
)
from registry import select_skill, sha256_file, tree_sha256
from telemetry import atomic_write_json, initialize_data_dir, record_event, resolve_data_dir, utc_now

MODES = {"deterministic", "full_test", "paired", "dry_run"}
VERDICTS = {
    "deterministic": {"PASS", "FAIL"},
    "full_test": {"BETTER", "TIE", "WORSE"},
    "paired": {"BETTER", "TIE", "WORSE"},
    "dry_run": {"BETTER", "TIE", "WORSE", "PASS", "FAIL"},
}


def manifest_path(data_dir: Path, candidate_id: str) -> Path:
    return data_dir / "evolution" / candidate_id / "manifest.json"


def load_manifest(data_dir: Path, candidate_id: str) -> tuple[Path, dict[str, Any]]:
    path = manifest_path(data_dir, candidate_id)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        raise SystemExit("Evolution candidate not found.")
    return path, value


def isolated_tree(path: Path, expected: Path, label: str) -> Path:
    if path.is_symlink() or path.resolve() != expected.resolve() or not path.is_dir():
        raise SystemExit(f"{label} is missing or no longer isolated.")
    return path.resolve()


def candidate_tree(path: Path, manifest: dict[str, Any]) -> Path:
    return isolated_tree(Path(manifest["candidate_path"]), path.parent / "candidate", "Candidate")


def baseline_tree(path: Path, manifest: dict[str, Any]) -> Path:
    baseline = isolated_tree(Path(manifest["baseline_path"]), path.parent / "baseline", "Baseline")
    if tree_sha256(baseline) != manifest["source_tree_sha256"]:
        raise SystemExit("Baseline snapshot changed after candidate preparation.")
    return baseline


def write_review_diff(path: Path, baseline: Path, candidate: Path) -> Path:
    review_path = path.parent / "review.diff"
    baseline_files = {p.relative_to(baseline) for p in baseline.rglob("*") if p.is_file() and not p.is_symlink()}
    candidate_files = {p.relative_to(candidate) for p in candidate.rglob("*") if p.is_file() and not p.is_symlink()}
    chunks: list[str] = []
    for relative in sorted(baseline_files | candidate_files, key=lambda item: item.as_posix().lower()):
        old_bytes = (baseline / relative).read_bytes() if relative in baseline_files else b""
        new_bytes = (candidate / relative).read_bytes() if relative in candidate_files else b""
        if old_bytes == new_bytes:
            continue
        try:
            old_lines = old_bytes.decode("utf-8").splitlines()
            new_lines = new_bytes.decode("utf-8").splitlines()
        except UnicodeDecodeError:
            chunks.append(f"Binary files a/{relative.as_posix()} and b/{relative.as_posix()} differ\n")
            continue
        chunks.extend(
            line + "\n"
            for line in difflib.unified_diff(
                old_lines,
                new_lines,
                fromfile=f"a/{relative.as_posix()}",
                tofile=f"b/{relative.as_posix()}",
                lineterm="",
            )
        )
    review_path.write_text("".join(chunks), encoding="utf-8")
    return review_path


def prepare_candidate(
    data_dir: Path, skill_name: str, skill_path: str | None, reason: str
) -> dict[str, Any]:
    if not reason.strip():
        raise SystemExit("An explicit human reason is required.")
    registry = load_registry(data_dir)
    skill = select_skill(registry, skill_name, skill_path)
    source = ensure_archivable(skill, registry, require_runtime_release=False)
    candidate_id = str(uuid.uuid4())
    root = data_dir / "evolution" / candidate_id
    baseline = root / "baseline"
    candidate = root / "candidate"
    root.mkdir(parents=True)
    shutil.copytree(source, baseline)
    shutil.copytree(source, candidate)
    source_hash = tree_sha256(source)
    manifest = {
        "schema_version": 1,
        "candidate_id": candidate_id,
        "status": "PREPARED",
        "created_at": utc_now(),
        "record_id": skill["record_id"],
        "skill_id": skill["skill_id"],
        "source_path": str(source),
        "source_tree_sha256": source_hash,
        "baseline_path": str(baseline),
        "candidate_path": str(candidate),
        "reason": reason.strip(),
        "evaluations": [],
    }
    path = manifest_path(data_dir, candidate_id)
    atomic_write_json(path, manifest)
    record_event(
        data_dir,
        "candidate_prepared",
        {
            "candidate_id": candidate_id,
            "skill_id": skill["skill_id"],
            "record_id": skill["record_id"],
            "attribution_source": "MANUAL",
            "outcome": "UNKNOWN",
        },
    )
    return {
        "candidate_id": candidate_id,
        "skill": skill["skill_id"],
        "source_path": str(source),
        "candidate_path": str(candidate),
        "manifest_path": str(path),
        "instruction": "Edit only candidate_path. The live Skill remains unchanged.",
    }


def record_evaluation(
    data_dir: Path,
    candidate_id: str,
    mode: str,
    verdict: str,
    evaluator: str,
    prompt_id: str,
    note: str,
    evidence_path: Path | str | None = None,
    held_out: bool = False,
) -> dict[str, Any]:
    mode = mode.lower()
    verdict = verdict.upper()
    if mode not in MODES or verdict not in VERDICTS[mode]:
        raise SystemExit("Unsupported evaluation mode or verdict.")
    if not evaluator.strip() or not prompt_id.strip():
        raise SystemExit("Evaluator and prompt id are required.")
    path, manifest = load_manifest(data_dir, candidate_id)
    if manifest["status"] != "PREPARED":
        raise SystemExit("Evaluations can only be added to a prepared candidate.")
    candidate_hash = tree_sha256(candidate_tree(path, manifest))
    if mode in {"full_test", "paired"} and not held_out:
        raise SystemExit("Full and paired evaluations must use a held-out prompt.")
    evidence = Path(evidence_path).resolve() if evidence_path else None
    if mode in {"full_test", "paired"} and (not evidence or not evidence.is_file()):
        raise SystemExit("Full and paired evaluations require a real evidence file.")
    evaluation_id = str(uuid.uuid4())
    stored_evidence = None
    evidence_sha256 = None
    if evidence:
        evidence_dir = path.parent / "evidence"
        evidence_dir.mkdir(exist_ok=True)
        stored = evidence_dir / f"{evaluation_id}{evidence.suffix or '.txt'}"
        shutil.copy2(evidence, stored)
        stored_evidence = str(stored)
        evidence_sha256 = sha256_file(stored)
    item = {
        "evaluation_id": evaluation_id,
        "timestamp": utc_now(),
        "mode": mode,
        "verdict": verdict,
        "evaluator": evaluator.strip(),
        "prompt_id": prompt_id.strip(),
        "note": note.strip(),
        "held_out": bool(held_out),
        "evidence_path": stored_evidence,
        "evidence_sha256": evidence_sha256,
        "source_tree_sha256": manifest["source_tree_sha256"],
        "candidate_tree_sha256": candidate_hash,
    }
    manifest["evaluations"].append(item)
    atomic_write_json(path, manifest)
    return item


def record_proposal(data_dir: Path, candidate_id: str, summary: str) -> dict[str, Any]:
    if not summary.strip():
        raise SystemExit("A concrete proposal summary is required.")
    path, manifest = load_manifest(data_dir, candidate_id)
    if manifest["status"] != "PREPARED":
        raise SystemExit("A proposal can only be recorded for a prepared candidate.")
    current_candidate = candidate_tree(path, manifest)
    manifest["proposal_summary"] = summary.strip()
    manifest["proposal_recorded_at"] = utc_now()
    manifest["proposal_candidate_tree_sha256"] = tree_sha256(current_candidate)
    atomic_write_json(path, manifest)
    return {
        "candidate_id": candidate_id,
        "proposal_summary": manifest["proposal_summary"],
        "candidate_path": manifest["candidate_path"],
    }


def promotion_gate(manifest: dict[str, Any], candidate_hash: str | None = None) -> dict[str, Any]:
    gate = core_promotion_gate(manifest)
    evaluations = manifest.get("evaluations", [])
    required = [item for item in evaluations if item.get("mode") in {"deterministic", "full_test", "paired"}]
    reasons = list(gate["reasons"])
    if candidate_hash:
        stale = [
            item for item in required
            if item.get("candidate_tree_sha256") != candidate_hash
            or item.get("source_tree_sha256") != manifest.get("source_tree_sha256")
        ]
        if stale:
            reasons.append("Candidate or source changed after a required evaluation; rerun the evaluation set.")
    for evaluation in evaluations:
        if evaluation.get("mode") not in {"full_test", "paired"}:
            continue
        evidence = Path(evaluation.get("evidence_path") or "")
        expected_hash = evaluation.get("evidence_sha256")
        if not evidence.is_file() or not expected_hash or sha256_file(evidence) != expected_hash:
            reasons.append(f"Evaluation evidence is missing or changed: {evaluation['evaluation_id']}.")
    counts = dict(gate["counts"])
    counts["dry_run"] = sum(item.get("mode") == "dry_run" for item in evaluations)
    return {"status": "PASS" if not reasons else "BLOCKED", "reasons": reasons, "counts": counts}
def validate_live_target(data_dir: Path, manifest: dict[str, Any]) -> tuple[dict, dict, Path]:
    registry = load_registry(data_dir)
    matches = [x for x in registry["skills"] if x.get("record_id") == manifest["record_id"]]
    if len(matches) != 1:
        raise SystemExit("Registry target no longer resolves uniquely.")
    skill = matches[0]
    source = ensure_archivable(skill, registry, require_runtime_release=False)
    if os.path.normcase(str(source)) != os.path.normcase(str(Path(manifest["source_path"]).resolve())):
        raise SystemExit("Live Skill path changed after candidate preparation.")
    if tree_sha256(source) != manifest["source_tree_sha256"]:
        raise SystemExit("Live Skill changed after candidate preparation.")
    return registry, skill, source


def promotion_plan(data_dir: Path, candidate_id: str) -> dict[str, Any]:
    path, manifest = load_manifest(data_dir, candidate_id)
    if manifest["status"] != "PREPARED":
        raise SystemExit("Candidate is not awaiting promotion.")
    if not manifest.get("proposal_summary", "").strip():
        raise SystemExit("Record a concrete proposal before planning promotion.")
    _, _, source = validate_live_target(data_dir, manifest)
    candidate = candidate_tree(path, manifest)
    baseline = baseline_tree(path, manifest)
    candidate_hash = tree_sha256(candidate)
    if candidate_hash == manifest["source_tree_sha256"]:
        raise SystemExit("Candidate has no changes.")
    if manifest.get("proposal_candidate_tree_sha256") != candidate_hash:
        raise SystemExit("Candidate changed after the proposal was recorded; record the proposal again.")
    gate = promotion_gate(manifest, candidate_hash)
    if gate["status"] != "PASS":
        raise SystemExit("Promotion gate blocked: " + " ".join(gate["reasons"]))
    review_diff = write_review_diff(path, baseline, candidate)
    review_diff_hash = sha256_file(review_diff)
    phrase = f"APPROVE PROMOTE {manifest['skill_id']} {candidate_id}"
    approval = create_approval(
        data_dir,
        {
            "action": "PROMOTE",
            "candidate_id": candidate_id,
            "record_id": manifest["record_id"],
            "skill_id": manifest["skill_id"],
            "source_path": str(source),
            "candidate_path": str(candidate),
            "target_tree_sha256": manifest["source_tree_sha256"],
            "candidate_tree_sha256": candidate_hash,
            "proposal_summary": manifest["proposal_summary"],
            "review_diff_sha256": review_diff_hash,
            "required_approval_text": phrase,
        },
    )
    manifest["candidate_tree_sha256"] = candidate_hash
    manifest["promotion_approval_id"] = approval["approval_id"]
    atomic_write_json(path, manifest)
    return {
        "approval_id": approval["approval_id"],
        "candidate_id": candidate_id,
        "skill": manifest["skill_id"],
        "gate": gate,
        "source_tree_sha256": manifest["source_tree_sha256"],
        "candidate_tree_sha256": candidate_hash,
        "proposal_summary": manifest["proposal_summary"],
        "review_diff_path": str(review_diff),
        "review_diff_sha256": review_diff_hash,
        "required_user_reply": phrase,
        "expires_at": approval["expires_at"],
        "warning": "Promotion changes the live Skill. Execute only after the user returns the exact phrase.",
    }


def promotion_execute(data_dir: Path, approval_id: str, approval_text: str) -> dict[str, Any]:
    approval_path, approval = load_pending_approval(data_dir, approval_id, "PROMOTE")
    if approval_text != approval["required_approval_text"]:
        raise SystemExit("Approval text does not exactly match the plan.")
    manifest_path_value, manifest = load_manifest(data_dir, approval["candidate_id"])
    registry, skill, source = validate_live_target(data_dir, manifest)
    candidate = candidate_tree(manifest_path_value, manifest)
    baseline = baseline_tree(manifest_path_value, manifest)
    if tree_sha256(candidate) != approval["candidate_tree_sha256"]:
        raise SystemExit("Candidate changed after approval; create a new plan.")
    review_diff = write_review_diff(manifest_path_value, baseline, candidate)
    if sha256_file(review_diff) != approval["review_diff_sha256"]:
        raise SystemExit("Review diff changed after approval; create a new plan.")
    gate = promotion_gate(manifest, approval["candidate_tree_sha256"])
    if gate["status"] != "PASS":
        raise SystemExit("Promotion evidence changed or no longer passes.")
    root = manifest_path_value.parent
    live_backup = root / "pre-promotion-live"
    staging = source.parent / f".darwin-promote-{manifest['candidate_id']}"
    if live_backup.exists() or staging.exists():
        raise SystemExit("Promotion staging path already exists.")
    shutil.copytree(candidate, staging)
    try:
        shutil.move(str(source), str(live_backup))
        shutil.move(str(staging), str(source))
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        if not source.exists() and live_backup.exists():
            shutil.move(str(live_backup), str(source))
        raise
    promoted_hash = tree_sha256(source)
    manifest["status"] = "PROMOTED"
    manifest["promoted_at"] = utc_now()
    manifest["promoted_tree_sha256"] = promoted_hash
    manifest["live_backup_path"] = str(live_backup)
    atomic_write_json(manifest_path_value, manifest)
    skill["content_sha256"] = sha256_file(source / "SKILL.md")
    skill["tree_sha256"] = promoted_hash
    skill["status"] = "EVOLVED"
    save_registry(data_dir, registry)
    approval["status"] = "CONSUMED"
    approval["consumed_at"] = manifest["promoted_at"]
    approval["user_approval_text"] = approval_text
    atomic_write_json(approval_path, approval)
    record_event(data_dir, "candidate_promoted", {"candidate_id": manifest["candidate_id"], "skill_id": manifest["skill_id"]})
    return {
        "promoted": True,
        "candidate_id": manifest["candidate_id"],
        "path": str(source),
        "promoted_tree_sha256": promoted_hash,
        "rollback": "Create a separate plan-rollback approval.",
    }


def rollback_plan(data_dir: Path, candidate_id: str) -> dict[str, Any]:
    _, manifest = load_manifest(data_dir, candidate_id)
    if manifest["status"] != "PROMOTED":
        raise SystemExit("Candidate is not an active promoted version.")
    source = Path(manifest["source_path"]).resolve()
    if tree_sha256(source) != manifest["promoted_tree_sha256"]:
        raise SystemExit("Live Skill changed after promotion.")
    phrase = f"APPROVE ROLLBACK {manifest['skill_id']} {candidate_id}"
    approval = create_approval(
        data_dir,
        {
            "action": "ROLLBACK_EVOLUTION",
            "candidate_id": candidate_id,
            "record_id": manifest["record_id"],
            "skill_id": manifest["skill_id"],
            "source_path": str(source),
            "target_tree_sha256": manifest["promoted_tree_sha256"],
            "baseline_tree_sha256": manifest["source_tree_sha256"],
            "required_approval_text": phrase,
        },
    )
    return {
        "approval_id": approval["approval_id"],
        "candidate_id": candidate_id,
        "required_user_reply": phrase,
        "warning": "Rollback replaces the current live Skill with its pre-promotion snapshot.",
    }


def rollback_execute(data_dir: Path, approval_id: str, approval_text: str) -> dict[str, Any]:
    approval_path, approval = load_pending_approval(data_dir, approval_id, "ROLLBACK_EVOLUTION")
    if approval_text != approval["required_approval_text"]:
        raise SystemExit("Approval text does not exactly match the plan.")
    path, manifest = load_manifest(data_dir, approval["candidate_id"])
    source = Path(manifest["source_path"]).resolve()
    backup = Path(manifest["live_backup_path"]).resolve()
    if tree_sha256(source) != approval["target_tree_sha256"]:
        raise SystemExit("Live Skill changed after rollback approval.")
    if not backup.is_dir() or tree_sha256(backup) != approval["baseline_tree_sha256"]:
        raise SystemExit("Rollback snapshot is missing or changed.")
    rejected = path.parent / "rejected-promoted"
    if rejected.exists():
        raise SystemExit("Rollback destination already exists.")
    shutil.move(str(source), str(rejected))
    try:
        shutil.move(str(backup), str(source))
    except Exception:
        shutil.move(str(rejected), str(source))
        raise
    manifest["status"] = "ROLLED_BACK"
    manifest["rolled_back_at"] = utc_now()
    manifest["rejected_promoted_path"] = str(rejected)
    atomic_write_json(path, manifest)
    registry = load_registry(data_dir)
    skill = next(x for x in registry["skills"] if x["record_id"] == manifest["record_id"])
    skill["content_sha256"] = sha256_file(source / "SKILL.md")
    skill["tree_sha256"] = tree_sha256(source)
    skill["status"] = "DISCOVERED"
    save_registry(data_dir, registry)
    approval["status"] = "CONSUMED"
    approval["consumed_at"] = manifest["rolled_back_at"]
    approval["user_approval_text"] = approval_text
    atomic_write_json(approval_path, approval)
    record_event(data_dir, "candidate_rolled_back", {"candidate_id": manifest["candidate_id"], "skill_id": manifest["skill_id"]})
    return {"rolled_back": True, "candidate_id": manifest["candidate_id"], "path": str(source)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Darwin controlled Skill evolution")
    parser.add_argument("--data-dir")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--skill", required=True)
    prepare.add_argument("--path")
    prepare.add_argument("--reason", required=True)
    evaluate = sub.add_parser("record-eval")
    evaluate.add_argument("--candidate-id", required=True)
    evaluate.add_argument("--mode", required=True, choices=sorted(MODES))
    evaluate.add_argument("--verdict", required=True)
    evaluate.add_argument("--evaluator", required=True)
    evaluate.add_argument("--prompt-id", required=True)
    evaluate.add_argument("--note", default="")
    evaluate.add_argument("--evidence-file")
    evaluate.add_argument("--held-out", action="store_true")
    proposal = sub.add_parser("record-proposal")
    proposal.add_argument("--candidate-id", required=True)
    proposal.add_argument("--summary", required=True)
    promote = sub.add_parser("plan-promote")
    promote.add_argument("--candidate-id", required=True)
    execute = sub.add_parser("execute-promote")
    execute.add_argument("--approval-id", required=True)
    execute.add_argument("--approval-text", required=True)
    rollback = sub.add_parser("plan-rollback")
    rollback.add_argument("--candidate-id", required=True)
    restore = sub.add_parser("rollback")
    restore.add_argument("--approval-id", required=True)
    restore.add_argument("--approval-text", required=True)
    show = sub.add_parser("show")
    show.add_argument("--candidate-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    data_dir = initialize_data_dir(resolve_data_dir(args.data_dir), write_locator=not bool(args.data_dir))
    if args.command == "prepare":
        result = prepare_candidate(data_dir, args.skill, args.path, args.reason)
    elif args.command == "record-eval":
        result = record_evaluation(
            data_dir, args.candidate_id, args.mode, args.verdict, args.evaluator,
            args.prompt_id, args.note, args.evidence_file, args.held_out,
        )
    elif args.command == "record-proposal":
        result = record_proposal(data_dir, args.candidate_id, args.summary)
    elif args.command == "plan-promote":
        result = promotion_plan(data_dir, args.candidate_id)
    elif args.command == "execute-promote":
        result = promotion_execute(data_dir, args.approval_id, args.approval_text)
    elif args.command == "plan-rollback":
        result = rollback_plan(data_dir, args.candidate_id)
    elif args.command == "rollback":
        result = rollback_execute(data_dir, args.approval_id, args.approval_text)
    else:
        result = load_manifest(data_dir, args.candidate_id)[1]
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
