# Darwin Skill Steward v0.4.0

## 快速使用：Skill 管家

在 Agent 里说“盘点 Skills”就能用，每次只盘点当前这个 Agent。也可以直接运行命令（`--agent` 可选 codex / claude / workbuddy / doubao；不写时自动识别当前 Agent）：

```text
python scripts/darwin.py --agent claude inventory   # 列出当前 Agent 的全部 Skill：来源、使用次数、最近使用
python scripts/darwin.py advise        # 编号建议：可以删除 / 建议优化 / 保持现状，每条附理由
python scripts/darwin.py delete 1、3    # 删除 = 移进回收站 ~/.darwin/recycle-bin，可恢复
python scripts/darwin.py restore <回收站编号>
python scripts/darwin.py align 12      # 同一个 Skill 的多份副本统一成一个版本
python scripts/darwin.py draft 7       # 优化：先生成草稿，确认后再 apply-draft
python scripts/darwin.py checkup       # 每月体检：只报告新变化
```

使用次数来自本机记录：Codex 会话、Claude Code 对话、WorkBuddy 使用日志。豆包没有可读取的记录，显示为“无法统计”。只有自己安装的 Skill 会被移动；系统自带和插件带的 Skill 只给建议。报告生成后如果 Skill 被改过，操作会被拒绝。

下面是 Darwin 的底层治理与受控进化机制。

Darwin is a conservative, controlled Skill evolution system for multiple Agent runtimes:

`Observe -> Diagnose -> Candidate -> Validate -> Human Approve -> Promote or Roll Back`

It inventories Skills, keeps system/official assets protected, collects local evidence, and generates `KEEP / OBSERVE / ARCHIVE / MERGE / EVOLVE` recommendations. For EVOLVE, it edits and tests only an isolated candidate. Promotion and rollback both require separate exact human approval. It never permanently deletes Skills.

## Runtime support

Darwin separates runtime-independent governance from Agent-specific adapters. `darwin_core` owns the runtime contract, durable storage boundary, and evidence-gated promotion policy.

- **Codex:** full existing governance, observation, approval, promotion, and rollback workflow.
- **Claude Code:** discovers user/project Skills, translates Hook turn events, and packages candidates as Claude plugins.
- **Claude Cowork:** packages candidates as uploadable custom plugins and produces a reviewed manual installation plan.
- **WorkBuddy:** discovers `.workbuddy/skills` (user and project; `~/.agents/skills` belongs to Codex), validates documented metadata, packages a Skill ZIP, and produces a reviewed upload plan.
- **Doubao client:** scans only user-selected exports, produces a candidate ZIP, and prepares a manual upload plan. Automatic installation and runtime telemetry remain unavailable until a stable public interface is verified.

Use `scripts/runtime.py` to list assets, package candidates, and generate platform-specific import plans. See the exact capability levels in [the runtime capability matrix](docs/runtime-capability-matrix.md).

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
darwin-skill-steward/
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
│   ├── evolution.py
│   ├── run-observer.ps1
│   └── runtime.py
├── adapters/
│   ├── codex.py
│   ├── claude.py
│   ├── workbuddy.py
│   └── doubao.py
├── config/defaults.json
├── darwin_core/frontmatter.py
├── requirements.txt
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
evolution/<candidate-id>/          baseline, candidate, evaluations, promotion snapshot
```

Event metadata contains hashes and lengths. Text evidence is redacted by default, capped at 4,000 characters, and expires after 30 days when pruning runs. Set `DARWIN_CAPTURE_MODE=off` to disable text capture or `full` to keep capped unredacted text locally. Review privacy implications before using `full`.

## Local development

The Hook telemetry path uses only the Python standard library. Registry scanning and packaging use PyYAML's safe loader so folded, literal, quoted, UTF-8, empty, and invalid frontmatter are handled consistently. Install the declared dependency before local development:

```text
python -m pip install -r requirements.txt
```

On this Windows Codex desktop installation, the bundled interpreter is under:

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

Before Darwin can generate an archive plan, the registry record must explicitly say that the target runtime no longer needs that copy:

```text
python scripts/registry.py set-runtime-dependency --skill old-skill --path <exact-path> --status not-required
```

This declaration is stored separately for each discovered copy and is bound to that copy's tree hash, runtime, and deployment. If the content changes afterwards, archive planning is refused until you rescan and re-confirm. Cross-runtime mirrors remain observations unless the relevant runtime copy is explicitly released.

Archive is a two-step action:

```text
python scripts/archive.py plan --skill old-skill
```

The plan returns a one-time id, destination, tree hash, expiry, rollback path, and exact approval phrase. Darwin must show this plan and wait. After the user personally returns the exact phrase:

```text
python scripts/archive.py execute --approval-id <id> --approval-text "APPROVE ARCHIVE old-skill"
```

Restore requires a separate plan and approval. There is deliberately no delete command.

## Controlled evolution

`evolution.py prepare` copies one manageable Skill into an isolated candidate directory. The source remains unchanged while the agent edits and tests the candidate. Before promotion, `record-proposal` stores a concrete description of the candidate change. Promotion is blocked unless deterministic validation passes, at least one real held-out `full_test` favors the candidate, and at least three independent paired evaluators produce a strict `BETTER` majority.

Dry runs and judge-only scores never pass the gate. Full and paired evaluations must be marked held-out and attach an evidence file, which Darwin copies and hashes inside the candidate record. Every required evaluation is tied to the exact candidate hash it tested, so later edits invalidate the evaluation set. `plan-promote` generates a unified `review.diff` and creates a one-time approval tied to the source, candidate, and review hashes. `execute-promote` rechecks those hashes and all evaluation evidence, preserves the live source as a rollback snapshot, and then installs the candidate. Rollback has a separate plan and exact approval.

## Evidence boundary

- Hook prompt/stop events have `attribution_source=UNKNOWN` and `outcome=UNKNOWN`.
- Only `PLATFORM`, `MANAGED_SELF_REPORT`, and `MANUAL` invocation attribution enters high-confidence usage counts.
- `INFERRED` can support triage, never high-confidence health metrics.
- Explicit outcomes link to the same Skill and turn; unlinked labels are ignored by health scoring.
- Structural relationships are separate: `SAME_NAME`, `SAME_SKILL_MD`, `SAME_TREE`, and `SIMILAR_INSTRUCTIONS`. `CROSS_RUNTIME_MIRROR` is an independent deployment flag.
- Archived copies are not deployed, so they never count as a duplicate of, or a replacement for, a live Skill.
- Only a complete `SAME_TREE` comparison can become a duplicate-cleanup candidate. Matching `SKILL.md` files or similar text remain observations when other files differ.
- Plugin cache entries are active only when a `latest` link or installation registration identifies the selected version. Unresolved cache entries remain `CACHED_VERSION_UNKNOWN` and never become cleanup candidates.
- `ARCHIVE` requires dated complete coverage, sufficient inactivity, a viable replacement, a complete tree fingerprint, and explicit confirmation that the target runtime no longer needs that copy. Missing logs alone are never enough.
- `EVOLVE` opens an isolated candidate workflow; it never authorizes a live mutation by itself.

See [the two-round design review](docs/DESIGN_REVIEW.md), [managed telemetry protocol](docs/MANAGED_SKILL_PROTOCOL.md), and [acceptance plan](ACCEPTANCE.md).
