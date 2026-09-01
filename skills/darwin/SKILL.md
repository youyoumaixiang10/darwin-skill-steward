---
name: darwin
description: Audit, manage, and recommend actions for Codex Skills using explicit evidence boundaries. Use when a user asks to inspect, organize, archive, merge, monitor, health-check, or consider evolving Skills. It never auto-evolves or permanently deletes Skills.
---

# Darwin

Darwin v0.1 is a Skill asset manager and decision aid. Its operating loop is:

`Observe -> Manage -> Recommend -> Human Approve`

It may recommend `KEEP`, `OBSERVE`, `ARCHIVE`, `MERGE`, or `EVOLVE`. It does not mutate Skill instructions, run evolution, promote candidates, or permanently delete anything.

## Non-negotiable rules

- Treat `UNKNOWN` as unknown, never as success.
- Keep structural evidence separate from behavioral evidence, explicit human feedback, and controlled experiments.
- Do not claim a Skill was invoked unless an event names it and records its attribution source.
- Absence of observed use is not proof of non-use unless coverage is explicitly `COMPLETE`.
- Official, system, and plugin-bundled Skills are protected by default.
- Default cleanup means reversible archive, never permanent deletion.
- Before any archive or restore, show the exact target, function, evidence, destination, and rollback path; proceed only after the user gives the exact approval phrase produced by the plan command.
- Do not generate the approval phrase on the user's behalf or treat a vague acknowledgement as approval.

## Workflow

1. Resolve the plugin root from this Skill's location, then use the scripts under `<plugin-root>/scripts/`.
2. Run `registry.py scan` and inspect its summary. A first scan supports structure findings, not historical usage claims.
3. Run `health.py report --format markdown`. State the report's limitations before recommendations.
4. Present recommendations with evidence lanes: `STRUCTURAL`, `BEHAVIORAL`, `HUMAN`, and `EXPERIMENTAL`.
5. For `ARCHIVE`, run `archive.py plan --skill <name>`, show the plan, and wait. Only after the user returns the exact phrase, run `archive.py execute` with that phrase.
6. For `EVOLVE`, create or present a recommendation only. Mutation, eval, and promotion are outside v0.1.

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
```

Use `--data-dir <path>` in tests or manual development. Installed Hook runs use `PLUGIN_DATA` and create a local locator so later CLI commands resolve the same data directory.

## Attribution and outcomes

Codex currently exposes no public `SkillInvoked` Hook. `UserPromptSubmit` and `Stop` provide turn evidence only. A Skill invocation must use an attribution source: `PLATFORM`, `MANAGED_SELF_REPORT`, `MANUAL`, `INFERRED`, or `UNKNOWN`. Exclude `INFERRED` and `UNKNOWN` from high-confidence usage metrics.

Valid outcomes are `POSITIVE`, `REFINEMENT`, `FAILURE`, and `UNKNOWN`. Only explicit outcome events enter the known-outcome denominator.

For detailed definitions, read [references/evidence-model.md](references/evidence-model.md).
