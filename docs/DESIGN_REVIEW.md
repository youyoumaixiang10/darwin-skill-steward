# Darwin for Codex v0.1 — two-round design review

Review completed before implementation. Date: 2026-08-31 (Asia/Shanghai).

## Round 1: capability and epistemic integrity

Findings and corrections:

1. Codex documents `UserPromptSubmit`, `Stop`, and `SessionEnd`, but no public `SkillInvoked` Hook. The architecture therefore records turn evidence separately from Skill attribution.
2. `Stop` means a turn stopped. It does not prove success. Every Hook-created turn result is `UNKNOWN` until an explicit outcome event exists.
3. Missing invocation records do not prove non-use. Inactivity may support `ARCHIVE` only when coverage is explicitly `COMPLETE`, the observation window is long enough, and structural overlap also exists.
4. Transcript paths are convenient but not a stable Hook interface. Darwin does not parse transcripts as a core dependency.
5. Prompt and response text can contain sensitive data. Event metadata stores hashes and lengths; short-term text evidence is local, redacted by default, capped, and expirable.

## Round 2: mutation safety and operational resilience

Findings and corrections:

1. A script cannot cryptographically distinguish user approval from agent-supplied text. The implementation combines an exact one-time approval phrase, a 24-hour plan record, and a meta-skill rule forbidding Codex from supplying that phrase for the user.
2. Permanent deletion is omitted. Archive uses a move into `PLUGIN_DATA`, records source/hash/approval, and has a separately approved restore path.
3. System, official, and plugin-bundled paths are protected both in registry metadata and again during execution. Symlinked targets and paths outside scanned roots are rejected.
4. The target tree hash is checked again at execution. Any change invalidates the approval plan.
5. Hooks can run concurrently. Event writes use an exclusive lock; lock contention falls back to one-event spool files rather than corrupting or dropping evidence.
6. The plugin root should not hold persistent state. Runtime state resolves from `PLUGIN_DATA`; a locator contains only that path for later manual CLI use.

## Accepted residual limitations

- `MANAGED_SELF_REPORT` is a strong convention, not a platform-native invocation event.
- Text-overlap detection is an inference and can produce false positives; it never authorizes mutation.
- Exact approval phrases are an audit and process guard, not proof of human identity.
- v0.1 recommends `EVOLVE` but contains no mutation, eval, or promotion engine.
