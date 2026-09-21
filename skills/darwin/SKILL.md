---
name: darwin
description: Audit, package, manage, and safely evolve Skills across Codex, Claude Code/Cowork, WorkBuddy, and exported Doubao assets using explicit feedback, isolated candidates, real old-versus-new tests, human-approved promotion, and reversible rollback. Use for Skill health, duplication, archiving, cross-Agent packaging, improvement, evaluation, or controlled evolution.
---

# Darwin

Darwin v0.3.1 is a controlled cross-Agent Skill evolution system. Its operating loop is:

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
- Treat `SAME_SKILL_MD`, `SAME_TREE`, and `SIMILAR_INSTRUCTIONS` as different findings. Text similarity alone never justifies `MERGE`.
- Treat `CROSS_RUNTIME_MIRROR` as a deployment dependency. Do not archive one runtime's copy until that runtime is explicitly marked as no longer needing it.
- Before any archive, restore, promotion, or rollback, show the exact target, evidence, hashes, destination, and rollback path; proceed only after the user gives the exact approval phrase produced by the plan command.
- Do not generate the approval phrase on the user's behalf or treat a vague acknowledgement as approval.

## Workflow

1. Resolve the plugin root from this Skill's location, then use the scripts under `<plugin-root>/scripts/`.
2. Run `registry.py scan` and inspect its summary. A first scan supports structure findings, not historical usage claims.
3. Run `health.py report --format markdown`. State the report's limitations before recommendations.
4. Present recommendations with evidence lanes: `STRUCTURAL`, `BEHAVIORAL`, `HUMAN`, and `EXPERIMENTAL`.
5. For `ARCHIVE`, first record that the target runtime no longer needs the exact copy, then use the two-step `archive.py` flow.
6. For `EVOLVE`, prepare one isolated candidate with an explicit human reason. Edit only the returned `candidate_path`.
7. Use proposal prompts to improve the candidate, then run `record-proposal` with a concrete summary. Validate it on separate realistic prompts. Run deterministic validators first. Run the original and candidate with the same task, model, settings, permissions, and budget.
8. Record at least one real `full_test` and three independent paired comparisons. Do not describe a dry run as a real test.
9. Run `plan-promote`, show its complete result, and stop. Execute only after the user personally returns the exact phrase.
10. If a promoted version regresses, use the separate `plan-rollback` and `rollback` approval flow.

## Cross-Agent workflow

- Use `scripts/runtime.py` for non-Codex discovery, candidate packaging, and reviewed import plans.
- Claude Code discovery covers user and project `.claude/skills` roots. Candidate packages use the documented Claude plugin structure. Claude Code Hook events remain turn evidence only.
- Claude Cowork accepts a reviewed custom plugin ZIP. Discovery requires an explicit exported Skill root because Cowork does not expose a stable local installed-plugin directory to Darwin.
- WorkBuddy discovery covers `.agents/skills`; packaging enforces its documented `SKILL.md` metadata and produces an uploadable ZIP.
- Doubao discovery requires an explicit exported Skill root. Darwin produces a reviewed ZIP and manual client import plan because no stable public automatic-install or invocation telemetry interface has been verified.
- A manual import plan is not proof of installation. Record promotion success only after the user verifies the native Skill in the target runtime.

## Commands

Use a Python 3 interpreter. On Windows without Python on `PATH`, the Codex desktop runtime includes one; see the README for discovery instructions.

```text
python scripts/registry.py scan
python scripts/registry.py list
python scripts/telemetry.py summary
python scripts/health.py report --format markdown
python scripts/registry.py set-runtime-dependency --skill <skill-name> --path <exact-path> --status not-required
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
python scripts/runtime.py --runtime claude-code list
python scripts/runtime.py --runtime claude-cowork --root <export-root> package --asset <skill-id> --destination <output-dir>
python scripts/runtime.py --runtime workbuddy package --asset <skill-id> --destination <output-dir>
python scripts/runtime.py --runtime doubao --root <export-root> plan-apply --asset <skill-id> --package <zip-path>
python scripts/runtime.py --runtime doubao --root <export-root> plan-rollback --asset <skill-id> --package <prior-zip-path>
```

Use `--data-dir <path>` in tests or manual development. Installed Hook runs use `PLUGIN_DATA` and create a local locator so later CLI commands resolve the same data directory.

## Attribution and outcomes

Codex currently exposes no public `SkillInvoked` Hook. `UserPromptSubmit` and `Stop` provide turn evidence only. A Skill invocation must use an attribution source: `PLATFORM`, `MANAGED_SELF_REPORT`, `MANUAL`, `INFERRED`, or `UNKNOWN`. Exclude `INFERRED` and `UNKNOWN` from high-confidence usage metrics.

Valid outcomes are `POSITIVE`, `REFINEMENT`, `FAILURE`, and `UNKNOWN`. Only explicit outcome events enter the known-outcome denominator.

For detailed definitions, read [references/evidence-model.md](references/evidence-model.md).
