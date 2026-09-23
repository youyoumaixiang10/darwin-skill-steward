# Acceptance plan

## Automated checks

Run from the plugin root with Python 3:

```text
python -m unittest discover -s tests -v
python <plugin-creator>/scripts/validate_plugin.py .
python <skill-creator>/scripts/quick_validate.py skills/darwin
```

The suite verifies:

- Hook-created results remain `UNKNOWN`.
- secrets are redacted from short-term evidence;
- concurrent event writes remain readable;
- system Skills are protected;
- folded, literal, quoted, UTF-8, empty, and invalid YAML frontmatter share one parser result across scanning and packaging;
- duplicate relationships distinguish `SAME_SKILL_MD`, `SAME_TREE`, instruction similarity, and cross-runtime mirrors;
- plugin inventory separates active assets from inactive cached versions;
- duplicate and behavior recommendations preserve evidence lanes;
- missing telemetry alone cannot produce `ARCHIVE`;
- archive planning fails until the target runtime dependency is explicitly marked `NOT_REQUIRED`;
- archive execution fails without exact approval;
- changed targets invalidate approval;
- content changed after the runtime dependency release blocks archive planning until a rescan and re-confirmation;
- archive approvals bind the runtime, deployment, and runtime targets of the exact copy;
- archived copies are excluded from duplicate and replacement evidence for live Skills;
- candidate packaging refuses destinations inside the live Skill tree;
- the Skill steward discovers Codex, Claude Code, WorkBuddy, and Doubao Skills with their source (built-in, plugin, or user-installed);
- steward usage counts real use only: Codex SKILL.md reads and explicit picks, Claude Skill calls and slash commands, and the WorkBuddy usage log. System-prompt listings and Skill edits are excluded;
- steward advice numbers every delete, optimize, align, and collision item, and each item carries a reason;
- steward delete moves only unchanged user-installed Skills into a recycle bin and can restore them; built-in, plugin, linked, and out-of-root Skills are refused;
- steward optimization edits a draft, shows the diff, and replaces the live Skill only through a separate apply step;
- steward checkup reports only changes since the previous report;
- archive is reversible;
- no permanent delete command exists;
- candidate preparation leaves the live Skill unchanged;
- a concrete proposal and reviewable diff are required before promotion;
- changed or missing evaluation evidence blocks promotion;
- candidate edits after evaluation invalidate the evaluation set;
- dry-run or judge-only evidence cannot pass the promotion gate;
- promotion requires deterministic, real full-test, and independent paired evidence;
- promotion and rollback require separate exact approvals and hash checks;
- manifest, Hook configuration, scripts, Schema files, and docs are present.

## Manual plugin acceptance

1. Add the plugin to a local marketplace and install it.
2. Start a new Codex task; plugins are picked up in new tasks.
3. Open `/hooks`, review the exact Darwin Hook definitions, and trust them.
4. Submit one prompt and let one turn stop.
5. Run `telemetry.py summary`; confirm prompt/stop events exist and outcomes show `UNKNOWN`.
6. Run `registry.py scan`, then `health.py report --format markdown`.
7. Confirm official/system Skills show protected `KEEP`, and the report states that first-run usage is unknown.
8. On a disposable user Skill, record `set-runtime-dependency --status not-required`, then run `archive.py plan`. Confirm nothing moves before the exact approval phrase is returned.
9. Approve, archive, create a restore plan, approve again, and confirm the original tree hash is restored.
10. On a disposable Skill, prepare and edit a candidate. Confirm the live Skill is unchanged.
11. Record the proposal, deterministic result, held-out full-test, and three paired results. Confirm dry-run-only evidence cannot produce a promotion plan.
12. Plan promotion and inspect the generated `review.diff`. Approve promotion, then separately plan and approve rollback. Confirm the original tree hash is restored.

Passing local unit tests proves structure and deterministic safeguards. It does not prove Hook trust UI behavior or real Skill invocation attribution; those require the manual new-task test above.
