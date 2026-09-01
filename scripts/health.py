#!/usr/bin/env python3
"""Generate evidence-separated Skill health recommendations."""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
from pathlib import Path
import re
import uuid
from typing import Any

from telemetry import (
    exclusive_lock,
    initialize_data_dir,
    iter_events,
    load_json,
    parse_time,
    resolve_data_dir,
    utc_now,
)


HIGH_CONFIDENCE_ATTRIBUTION = {"PLATFORM", "MANAGED_SELF_REPORT", "MANUAL"}


def load_config(data_dir: Path) -> dict[str, Any]:
    defaults_path = Path(__file__).resolve().parent.parent / "config" / "defaults.json"
    config = load_json(defaults_path, {})
    override = load_json(data_dir / "config.json", {})
    config.update({key: value for key, value in override.items() if key != "health"})
    config["health"] = {**config.get("health", {}), **override.get("health", {})}
    return config


def tokens_for(path: Path) -> set[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace").lower()
    except OSError:
        return set()
    tokens = set(re.findall(r"[a-z0-9][a-z0-9_-]{1,}", text))
    for run in re.findall(r"[\u3400-\u9fff]{2,}", text):
        tokens.update(run[index : index + 2] for index in range(len(run) - 1))
    return tokens


def jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def overlap_map(skills: list[dict[str, Any]], threshold: float) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    token_cache = {item["record_id"]: tokens_for(Path(item["skill_md"])) for item in skills}
    for index, left in enumerate(skills):
        for right in skills[index + 1 :]:
            exact = bool(left.get("content_sha256") == right.get("content_sha256"))
            score = 1.0 if exact else jaccard(token_cache[left["record_id"]], token_cache[right["record_id"]])
            if exact or score >= threshold:
                evidence = {
                    "other_skill": right["skill_id"],
                    "other_record_id": right["record_id"],
                    "score": round(score, 3),
                    "status": "OBSERVED" if exact else "INFERRED",
                    "method": "exact_file_hash" if exact else "instruction_token_jaccard",
                }
                result[left["record_id"]].append(evidence)
                reverse = {**evidence, "other_skill": left["skill_id"], "other_record_id": left["record_id"]}
                result[right["record_id"]].append(reverse)
    return result


def event_targets_record(event: dict[str, Any], skill_id: str, record_id: str, ambiguous_name: bool) -> bool:
    if event.get("record_id"):
        return event.get("record_id") == record_id
    return not ambiguous_name and event.get("skill_id") == skill_id


def latest_coverage(
    events: list[dict[str, Any]], skill_id: str, record_id: str, ambiguous_name: bool
) -> dict[str, Any]:
    matches = [
        item
        for item in events
        if item.get("event_type") == "coverage_declared"
        and event_targets_record(item, skill_id, record_id, ambiguous_name)
    ]
    if not matches:
        return {"level": "NONE", "status": "UNKNOWN", "source": None, "since": None}
    item = matches[-1]
    return {
        "level": item.get("coverage", "NONE"),
        "status": item.get("evidence_status", "UNKNOWN"),
        "source": item.get("coverage_source"),
        "since": item.get("coverage_since") or item.get("timestamp"),
    }


def skill_metrics(
    events: list[dict[str, Any]], skill_id: str, record_id: str, ambiguous_name: bool
) -> dict[str, Any]:
    invocations = [
        item
        for item in events
        if item.get("event_type") == "skill_invocation"
        and event_targets_record(item, skill_id, record_id, ambiguous_name)
        and item.get("attribution_source") in HIGH_CONFIDENCE_ATTRIBUTION
    ]
    attributed_turns = {item.get("turn_id") for item in invocations if item.get("turn_id")}
    outcomes = [
        item
        for item in events
        if item.get("event_type") == "outcome"
        and event_targets_record(item, skill_id, record_id, ambiguous_name)
        and item.get("turn_id") in attributed_turns
        and item.get("outcome_status") == "EXPLICIT"
        and item.get("outcome") in {"POSITIVE", "REFINEMENT", "FAILURE"}
    ]
    counts = collections.Counter(item["outcome"] for item in outcomes)
    tags = collections.Counter(item.get("failure_tag") for item in outcomes if item.get("failure_tag"))
    latest = max((item.get("timestamp", "") for item in invocations), default=None)
    return {
        "attributed_invocations": len(invocations),
        "known_outcomes": len(outcomes),
        "positive": counts["POSITIVE"],
        "refinement": counts["REFINEMENT"],
        "failure": counts["FAILURE"],
        "unknown": max(0, len(invocations) - len(outcomes)),
        "failure_rate_known": round(counts["FAILURE"] / len(outcomes), 3) if outcomes else None,
        "failure_tags": dict(tags.most_common()),
        "last_attributed_invocation": latest,
    }


def days_since(value: str | None, now: dt.datetime) -> int | None:
    if not value:
        return None
    try:
        return max(0, (now - parse_time(value)).days)
    except ValueError:
        return None


def recommendation_for(
    skill: dict[str, Any],
    metrics: dict[str, Any],
    coverage: dict[str, Any],
    overlaps: list[dict[str, Any]],
    thresholds: dict[str, Any],
    now: dt.datetime,
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if skill.get("protected"):
        return "KEEP", [f"Protected by default: {skill.get('protection_reason') or skill.get('origin')}"]
    if skill.get("status") == "ARCHIVED":
        return "OBSERVE", ["Already archived; use the restore workflow if needed."]

    exact_overlap = [item for item in overlaps if item["status"] == "OBSERVED"]
    inferred_overlap = [item for item in overlaps if item["status"] == "INFERRED"]
    inactivity_days = days_since(metrics.get("last_attributed_invocation"), now)
    coverage_days = days_since(coverage.get("since"), now)
    no_use_days = inactivity_days if inactivity_days is not None else coverage_days
    replacement_available = any(
        item.get("other_attributed_invocations", 0) > 0 or item.get("other_protected", False)
        for item in overlaps
    )

    if (
        coverage["level"] == "COMPLETE"
        and coverage["status"] == "EXPLICIT"
        and coverage_days is not None
        and coverage_days >= int(thresholds["archive_inactivity_days"])
        and metrics["attributed_invocations"] == 0
        and no_use_days is not None
        and no_use_days >= int(thresholds["archive_inactivity_days"])
        and replacement_available
    ):
        return "ARCHIVE", [
            f"Complete coverage reports no attributed use for at least {no_use_days} days.",
            "An overlapping Skill has observed use or is protected; archive remains reversible and requires approval.",
        ]

    if exact_overlap:
        return "MERGE", [f"Exact SKILL.md duplicate of {exact_overlap[0]['other_skill']}."]

    known = metrics["known_outcomes"]
    failures = metrics["failure"]
    failure_rate = metrics["failure_rate_known"]
    if (
        metrics["attributed_invocations"] >= int(thresholds["minimum_known_outcomes"])
        and known >= int(thresholds["minimum_known_outcomes"])
        and failures >= int(thresholds["minimum_failures_for_evolve"])
        and failure_rate is not None
        and failure_rate >= float(thresholds["failure_rate_for_evolve"])
    ):
        reasons.append(f"{failures} explicit failures across {known} known outcomes.")
        if metrics["failure_tags"]:
            reasons.append(f"Repeated failure tags: {metrics['failure_tags']}")
        return "EVOLVE", reasons

    if inferred_overlap:
        return "MERGE", [
            f"Instruction overlap with {inferred_overlap[0]['other_skill']} is inferred, not proven.",
            "Review unique assets and workflows before any archive decision.",
        ]

    if (
        known >= int(thresholds["minimum_known_outcomes"])
        and failure_rate is not None
        and failure_rate < float(thresholds["failure_rate_for_keep"])
    ):
        return "KEEP", [f"Known-outcome failure rate is {failure_rate:.1%} across {known} explicit outcomes."]

    return "OBSERVE", [
        "Evidence is insufficient for a high-confidence action.",
        f"Coverage is {coverage['level']}; UNKNOWN outcomes remain separate.",
    ]


def build_report(data_dir: Path) -> dict[str, Any]:
    registry = load_json(data_dir / "registry.json", None)
    if not registry:
        raise SystemExit("Registry is missing. Run registry.py scan first.")
    config = load_config(data_dir)
    thresholds = config["health"]
    events = iter_events(data_dir)
    skills = registry.get("skills", [])
    name_counts = collections.Counter(item["skill_id"] for item in skills)
    overlaps = overlap_map(skills, float(thresholds["overlap_threshold"]))
    now = dt.datetime.now(dt.timezone.utc)
    results = []
    skill_by_record = {item["record_id"]: item for item in skills}
    metrics_by_record: dict[str, dict[str, Any]] = {}
    coverage_by_record: dict[str, dict[str, Any]] = {}
    for skill in skills:
        ambiguous_name = name_counts[skill["skill_id"]] > 1
        metrics_by_record[skill["record_id"]] = skill_metrics(
            events, skill["skill_id"], skill["record_id"], ambiguous_name
        )
        coverage_by_record[skill["record_id"]] = latest_coverage(
            events, skill["skill_id"], skill["record_id"], ambiguous_name
        )

    for skill in skills:
        ambiguous_name = name_counts[skill["skill_id"]] > 1
        metrics = metrics_by_record[skill["record_id"]]
        coverage = coverage_by_record[skill["record_id"]]
        skill_overlaps = []
        for overlap in overlaps.get(skill["record_id"], []):
            other_record = overlap["other_record_id"]
            other_skill = skill_by_record[other_record]
            skill_overlaps.append(
                {
                    **overlap,
                    "other_attributed_invocations": metrics_by_record[other_record]["attributed_invocations"],
                    "other_protected": other_skill.get("protected", False),
                }
            )
        recommendation, reasons = recommendation_for(
            skill, metrics, coverage, skill_overlaps, thresholds, now
        )
        results.append(
            {
                "skill_id": skill["skill_id"],
                "record_id": skill["record_id"],
                "description": skill.get("description", ""),
                "origin": skill["origin"],
                "protected": skill["protected"],
                "managed": skill.get("managed", False),
                "ambiguous_name": ambiguous_name,
                "recommendation": recommendation,
                "reasons": reasons,
                "metrics": metrics,
                "coverage": coverage,
                "evidence": {
                    "STRUCTURAL": {"status": "OBSERVED", "overlaps": skill_overlaps},
                    "BEHAVIORAL": {
                        "status": "OBSERVED" if metrics["attributed_invocations"] else "UNKNOWN",
                        "attributed_invocations": metrics["attributed_invocations"],
                    },
                    "HUMAN": {
                        "status": "EXPLICIT" if metrics["known_outcomes"] else "UNKNOWN",
                        "known_outcomes": metrics["known_outcomes"],
                    },
                    "EXPERIMENTAL": {"status": "UNKNOWN", "note": "Not produced by v0.1."},
                },
            }
        )

    counts = collections.Counter(item["recommendation"] for item in results)
    return {
        "schema_version": 1,
        "report_id": str(uuid.uuid4()),
        "generated_at": utc_now(),
        "summary": dict(sorted(counts.items())),
        "skills": results,
        "limitations": [
            "Codex exposes no public SkillInvoked Hook; only attributed invocation events count.",
            "UNKNOWN is never counted as POSITIVE.",
            "Near-overlap is an inference and requires human review.",
            "EVOLVE is a recommendation only; v0.1 does not mutate or promote Skills.",
        ],
    }


def append_history(data_dir: Path, report: dict[str, Any]) -> None:
    path = data_dir / "health-history.jsonl"
    snapshot = {
        "schema_version": 1,
        "report_id": report["report_id"],
        "generated_at": report["generated_at"],
        "summary": report["summary"],
    }
    with exclusive_lock(data_dir / ".health-history.lock") as acquired:
        if not acquired:
            return
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")) + "\n")


def markdown(report: dict[str, Any]) -> str:
    lines = ["# Darwin Skill Health Check", "", f"Report: `{report['report_id']}`", ""]
    lines.append("## Evidence limits")
    lines.extend(f"- {item}" for item in report["limitations"])
    lines.extend(["", "## Summary", ""])
    for action in ("KEEP", "OBSERVE", "ARCHIVE", "MERGE", "EVOLVE"):
        lines.append(f"- {action}: {report['summary'].get(action, 0)}")
    lines.extend(["", "## Skills", ""])
    for item in report["skills"]:
        metrics = item["metrics"]
        lines.append(f"### {item['skill_id']} — {item['recommendation']}")
        if item["description"]:
            lines.append(item["description"])
        lines.append(
            f"Attributed invocations: {metrics['attributed_invocations']}; "
            f"known outcomes: {metrics['known_outcomes']}; UNKNOWN: {metrics['unknown']}."
        )
        lines.extend(f"- {reason}" for reason in item["reasons"])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Darwin Skill health report")
    parser.add_argument("--data-dir")
    sub = parser.add_subparsers(dest="command", required=True)
    report = sub.add_parser("report")
    report.add_argument("--format", choices=("json", "markdown"), default="markdown")
    report.add_argument("--output")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    data_dir = initialize_data_dir(resolve_data_dir(args.data_dir), write_locator=not bool(args.data_dir))
    report = build_report(data_dir)
    append_history(data_dir, report)
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n" if args.format == "json" else markdown(report)
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
