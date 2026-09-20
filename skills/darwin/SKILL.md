---
name: darwin
description: Audit, manage, and safely evolve Codex Skills using explicit feedback, isolated candidates, real old-versus-new tests, human-approved promotion, and reversible rollback. Use for Skill health, duplication, archiving, improvement, evaluation, or controlled evolution.
---

# Darwin

Darwin v0.2 is a controlled Skill evolution system. Its operating loop is:

`Observe -> Diagnose -> Candidate -> Validate -> Human Approve -> Promote or Roll Back`

It may recommend `KEEP`, `OBSERVE`, `ARCHIVE`, `MERGE`, or `EVOLVE`. Evolution edits an isolated candidate only. A live Skill changes only after the user reviews a passing evaluation and returns the exact promotion phrase.

## Non-negotiable rules

- Treat `UNKNOWN` as unknown, never as success.
- Keep structural evidence separate from behavioral evidence, explicit human feedback, and controlled experiments.
- Do not claim a Skill was invoked unless an event names it and records its attribution source.
- Absence of observed use is not proof of non-use unless coverage is explicitly `COMPLETE`.
- Official, system, and plugin-bundled Skills are protected by default.
- Never edit a live Skill while preparing or testing a candidate.
- Dry runs, LLM scores, silence, and `UNKNOWN` outcomes cannot prove improvement.
- Promotion requires a passing deterministic check, a real `full_test` that favors the candidate, and a strict majority from at least three independent paired evaluators.
- Default cleanup means reversible archive, never permanent deletion.
- Before any archive, restore, promotion, or rollback, show the exact target, evidence, hashes, destination, and rollback path; proceed only after the user gives the exact approval phrase produced by the plan command.
- Do not generate the approval phrase on the user's behalf or treat a vague acknowledgement as approval.

## Workflow

1. Resolve the plugin root from this Skill's location, then use the scripts under `<plugin-root>/scripts/`.
2. Run `registry.py scan` and inspect its summary. A first scan supports structure findings, not historical usage claims.
3. Run `health.py report --format markdown`. State the report's limitations before recommendations.
4. Present recommendations with evidence lanes: `STRUCTURAL`, `BEHAVIORAL`, `HUMAN`, and `EXPERIMENTAL`.
5. For `ARCHIVE`, use the two-step `archive.py` flow.
6. For `EVOLVE`, prepare one isolated candidate with an explicit human reason. Edit only the returned `candidate_path`.
7. Use proposal prompts to improve the candidate, then run `record-proposal` with a concrete summary. Validate it on separate realistic prompts. Run deterministic validators first. Run the original and candidate with the same task, model, settings, permissions, and budget.
8. Record at least one real `full_test` and three independent paired comparisons. Do not describe a dry run as a real test.
9. Run `plan-promote`, show its complete result, and stop. Execute only after the user personally returns the exact phrase.
10. If a promoted version regresses, use the separate `plan-rollback` and `rollback` approval flow.

## Commands

Use a Python 3 interpreter. On Windows without Python on `PATH`, the Codex desktop runtime includes one; see the README for discovery instructions.

```text
python scripts/registry.py scan
python scripts/registry.py list
python scripts/telemetry.py summary
python scripts/health.py report --format markdown
python scripts/archive.py plan --skill <skill-name>
python scripts/archive.py execute --approval-id <id> --approval-text "APPROVE ARCHIVE <skill-name>"
python scripts/archive.py list
python scripts/archive.py plan-restore --archive-id <id>
python scripts/archive.py restore --approval-id <id> --approval-text "APPROVE RESTORE <archive-id>"
python scripts/evolution.py prepare --skill <skill-name> --reason "<explicit reason>"
python scripts/evolution.py record-proposal --candidate-id <id> --summary "<concrete proposed change>"
python scripts/evolution.py record-eval --candidate-id <id> --mode deterministic --verdict PASS --evaluator <name> --prompt-id <id>
python scripts/evolution.py record-eval --candidate-id <id> --mode full_test --verdict BETTER --evaluator <name> --prompt-id <heldout-id> --held-out --evidence-file <comparison-file>
python scripts/evolution.py record-eval --candidate-id <id> --mode paired --verdict BETTER --evaluator <judge> --prompt-id <heldout-id> --held-out --evidence-file <judgment-file>
python scripts/evolution.py plan-promote --candidate-id <id>
python scripts/evolution.py execute-promote --approval-id <id> --approval-text "APPROVE PROMOTE <skill> <candidate-id>"
python scripts/evolution.py plan-rollback --candidate-id <id>
python scripts/evolution.py rollback --approval-id <id> --approval-text "APPROVE ROLLBACK <skill> <candidate-id>"
```

Use `--data-dir <path>` in tests or manual development. Installed Hook runs use `PLUGIN_DATA` and create a local locator so later CLI commands resolve the same data directory.

## Attribution and outcomes

Codex currently exposes no public `SkillInvoked` Hook. `UserPromptSubmit` and `Stop` provide turn evidence only. A Skill invocation must use an attribution source: `PLATFORM`, `MANAGED_SELF_REPORT`, `MANUAL`, `INFERRED`, or `UNKNOWN`. Exclude `INFERRED` and `UNKNOWN` from high-confidence usage metrics.

Valid outcomes are `POSITIVE`, `REFINEMENT`, `FAILURE`, and `UNKNOWN`. Only explicit outcome events enter the known-outcome denominator.

For detailed definitions, read [references/evidence-model.md](references/evidence-model.md).
