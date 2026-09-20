"""Runtime-neutral promotion gate used by all Darwin adapters."""

from __future__ import annotations

from typing import Any


def promotion_gate(manifest: dict[str, Any]) -> dict[str, Any]:
    evaluations = manifest.get("evaluations", [])
    deterministic = [item for item in evaluations if item.get("mode") == "deterministic"]
    full_tests = [item for item in evaluations if item.get("mode") == "full_test"]
    paired_by_evaluator = {
        item.get("evaluator", str(index)): item
        for index, item in enumerate(evaluations)
        if item.get("mode") == "paired"
    }
    paired = list(paired_by_evaluator.values())
    better = sum(item.get("verdict") == "BETTER" for item in paired)
    reasons: list[str] = []
    if not deterministic or any(item.get("verdict") != "PASS" for item in deterministic):
        reasons.append("A passing deterministic validation with no failures is required.")
    if not any(item.get("verdict") == "BETTER" and item.get("held_out") for item in full_tests):
        reasons.append("A held-out full_test must judge the candidate BETTER.")
    if any(item.get("verdict") == "WORSE" for item in full_tests):
        reasons.append("A full_test regression blocks promotion.")
    if len(paired) < 3 or better <= len(paired) / 2:
        reasons.append("At least three independent paired judges with a strict BETTER majority are required.")
    return {
        "status": "PASS" if not reasons else "BLOCKED",
        "reasons": reasons,
        "counts": {"deterministic": len(deterministic), "full_test": len(full_tests), "paired": len(paired), "paired_better": better},
    }
