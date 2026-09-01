# Darwin for Codex v0.1

Darwin is a conservative Skill asset manager for Codex:

`Observe -> Manage -> Recommend -> Human Approve`

It inventories Skills, keeps system/official assets protected, collects local evidence, generates `KEEP / OBSERVE / ARCHIVE / MERGE / EVOLVE` recommendations, and can perform a reversible archive only after explicit approval. It does not auto-evolve, auto-promote, or permanently delete Skills.

## Official capability review

Re-verified against official OpenAI documentation on 2026-08-31:

- Plugins require `.codex-plugin/plugin.json`, can package Skills, and should be tested in a new conversation: [Build plugins](https://learn.chatgpt.com/docs/build-plugins).
- A Skill is a directory with `SKILL.md`; `name` and `description` are required, and activation can be explicit or implicit: [Build skills](https://learn.chatgpt.com/docs/build-skills).
- Plugin Hooks can use the default `hooks/hooks.json`; Hook changes require review/trust; plugin commands receive `PLUGIN_ROOT` and writable `PLUGIN_DATA`: [Hooks](https://learn.chatgpt.com/docs/hooks).
- `UserPromptSubmit` exposes `turn_id` and `prompt`; `Stop` exposes `turn_id` and `last_assistant_message`; the public event list has no `SkillInvoked` event: [Hooks event reference](https://learn.chatgpt.com/docs/hooks#hooks).
- Plugins are supported in Codex in the ChatGPT desktop app and Codex CLI, while the IDE extension does not support plugins: [Use plugins](https://learn.chatgpt.com/docs/plugins).

The manifest intentionally omits a `hooks` field because the documented default `hooks/hooks.json` discovery is sufficient and keeps the package compatible with the current local validator.

## Project layout

```text
darwin-for-codex/
├── .codex-plugin/plugin.json
├── hooks/hooks.json
├── skills/darwin/
│   ├── SKILL.md
│   ├── agents/openai.yaml
│   └── references/evidence-model.md
├── scripts/
│   ├── observe.py
│   ├── telemetry.py
│   ├── registry.py
│   ├── health.py
│   ├── archive.py
│   └── run-observer.ps1
├── config/defaults.json
├── schemas/
├── docs/
├── tests/
├── ACCEPTANCE.md
└── README.md
```

## Runtime data

Persistent state lives in `PLUGIN_DATA`, not the installed plugin tree:

```text
registry.json
events.jsonl
health-history.jsonl
archive-index.json
config.json                         optional local overrides
evidence/raw/YYYY-MM-DD/*.json     short-term text evidence
evidence/spool/*.json              contention fallback
approvals/*.json                   one-time action plans
archive/<record-id>/<archive-id>/  reversible Skill archives
evolution/                         reserved for recommendation dossiers
```

Event metadata contains hashes and lengths. Text evidence is redacted by default, capped at 4,000 characters, and expires after 30 days when pruning runs. Set `DARWIN_CAPTURE_MODE=off` to disable text capture or `full` to keep capped unredacted text locally. Review privacy implications before using `full`.

## Local development

All scripts use the Python standard library. On this Windows Codex desktop installation, the bundled interpreter is under:

```text
%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe
```

Use `--data-dir` before the subcommand for an isolated test store:

```text
python scripts/registry.py --data-dir .darwin-test scan --root tests/fixtures/skills
python scripts/health.py --data-dir .darwin-test report --format markdown
python scripts/telemetry.py --data-dir .darwin-test summary
```

Installed Hook commands resolve `PLUGIN_DATA` automatically. On Windows, `run-observer.ps1` tries a system Python/launcher and then the Codex bundled runtime.

## Approval and archive

Archive is a two-step action:

```text
python scripts/archive.py plan --skill old-skill
```

The plan returns a one-time id, destination, tree hash, expiry, rollback path, and exact approval phrase. Darwin must show this plan and wait. After the user personally returns the exact phrase:

```text
python scripts/archive.py execute --approval-id <id> --approval-text "APPROVE ARCHIVE old-skill"
```

Restore requires a separate plan and approval. There is deliberately no delete command.

## Evidence boundary

- Hook prompt/stop events have `attribution_source=UNKNOWN` and `outcome=UNKNOWN`.
- Only `PLATFORM`, `MANAGED_SELF_REPORT`, and `MANUAL` invocation attribution enters high-confidence usage counts.
- `INFERRED` can support triage, never high-confidence health metrics.
- Explicit outcomes link to the same Skill and turn; unlinked labels are ignored by health scoring.
- `ARCHIVE` requires a dated complete-coverage window, sufficient inactivity, and an overlapping Skill with observed use or protected availability; missing logs alone are never enough.
- `EVOLVE` is a recommendation only in v0.1.

See [the two-round design review](docs/DESIGN_REVIEW.md), [managed telemetry protocol](docs/MANAGED_SKILL_PROTOCOL.md), and [acceptance plan](ACCEPTANCE.md).
