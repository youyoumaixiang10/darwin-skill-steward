# Darwin Multi-Agent Architecture

## Decision

Darwin becomes a cross-agent Skill and workflow governance system. Its core owns the evidence, candidate, evaluation, approval, promotion, and rollback lifecycle. Each Agent product is represented by a separate adapter that knows how to discover, package, observe, and apply assets in that product.

Codex is no longer the product boundary. It remains the first fully implemented adapter and the migration reference.

## Product goal

Users should be able to manage an Agent capability as one governed asset even when its runtime is Codex, Claude Code, Claude Cowork, WorkBuddy, or the Doubao client. A user can inspect an asset, attach feedback, prepare an isolated candidate, compare it with the current version, review its diff, approve a promotion, and recover the prior version.

The same safety rules apply on every runtime:

- `UNKNOWN` is not success or non-use.
- Structural evidence, behavioral evidence, human feedback, and controlled experiments remain separate.
- Preparing and testing never change a live asset.
- System, official, bundled, symlinked, and out-of-root assets are protected by default.
- Archive is reversible; permanent deletion is outside Darwin.
- Promotion and rollback each require a new exact human approval.

## Scope and rollout

### Phase 1: extract the portable core

Move the current candidate lifecycle and policy logic behind runtime-neutral interfaces. Preserve Codex behavior through a Codex adapter. The repository stays named `darwin-for-codex` during this migration to avoid a premature public rename and broken installation links.

### Phase 2: first adapter set

Add adapters for:

1. **Codex** — existing plugin, Hook, marketplace, Skill directory discovery, and `PLUGIN_DATA` integration.
2. **Claude** — shared asset model for Claude Code and Claude Cowork. Claude Code may add local Hook observation; Cowork may package role plugins and use its own cloud/session surfaces.
3. **WorkBuddy** — package Skill, Hook, Agent, Rule, and MCP-facing assets using its documented extension model.
4. **Doubao client** — manage custom agents and Skills as governed assets. The initial adapter must support asset export, candidate generation, review, and a user-reviewed installation/update plan. Automatic installation, marketplace publishing, or runtime telemetry are enabled only after the actual client exposes and Darwin verifies a stable public interface for that operation.

### Phase 3: distribution rename

Only after at least two non-Codex adapters pass their contract tests should the project decide whether to rename the repository and publish a general `Darwin` release. This is a public migration decision, not an implementation side effect.

## Architecture

```text
Darwin Core
├── asset registry
├── evidence and feedback ledger
├── candidate workspace
├── evaluation gate
├── approval records
├── promotion and rollback snapshots
└── policy engine

Adapter contract
├── discover assets
├── classify protection and provenance
├── read/export a live asset
├── package a validated candidate
├── prepare an apply or rollback plan
└── optionally observe runtime events

Runtime packages
├── Codex adapter
├── Claude adapter
├── WorkBuddy adapter
└── Doubao adapter
```

The core never assumes a Hook exists. Observation is an optional adapter capability. An adapter that cannot observe invocations can still support manual feedback, evaluation, promotion planning, and rollback. Missing telemetry remains `UNKNOWN`.

The core also never assumes a runtime accepts a local folder. Packaging is an adapter responsibility. For example, an adapter may produce a Codex plugin, a Claude plugin, a WorkBuddy Skill package, or a Doubao import/update plan from the same approved candidate.

## Canonical asset model

Every managed asset has a Darwin record with:

- a stable Darwin record id;
- runtime and adapter id;
- native asset id and display name;
- source/provenance classification;
- protected status and reason;
- exported source tree hash;
- current live version or revision when the runtime exposes one;
- evidence references;
- candidate and promotion history.

The source tree hash is the cross-runtime comparison unit. Runtime-specific ids are retained for safe installation and rollback, but never used as a substitute for content verification.

## Promotion contract

The core retains the v0.2 gate:

1. a deterministic validation passes with no deterministic failure;
2. at least one held-out full test marks the candidate `BETTER`;
3. at least three independent paired evaluators yield a strict `BETTER` majority;
4. full-test and paired evidence files are copied and SHA-256 hashed;
5. the proposal, candidate, source, evaluation records, and review diff all match the planned versions;
6. a user supplies the exact one-time approval text.

An adapter may add stricter requirements, such as a platform review screen or an exportable native version id. It may not weaken the core gate.

## Runtime-specific boundaries

### Codex

Codex-specific concerns move behind the adapter: `.codex-plugin`, `hooks/hooks.json`, `PLUGIN_ROOT`, `PLUGIN_DATA`, Codex Skill roots, and personal marketplace installation. Codex Hook events remain turn evidence only unless a named Skill attribution event exists.

### Claude Code and Claude Cowork

The Claude adapter shares the agent-skill and plugin source where formats overlap, but exposes two capabilities. Claude Code can support local file and Hook-oriented observation. Cowork is treated as a managed plugin/session environment, where a promotion may require an exported plugin and user-visible native installation rather than a direct local replacement.

### WorkBuddy

The WorkBuddy adapter maps Darwin assets to its Skill, Hook, Agent, Rule, and MCP extension types. Its runtime must explicitly identify which installed asset received an update before Darwin records promotion success.

### Doubao client

The Doubao adapter starts from user-created agents and custom Skills. Darwin can create and evaluate a candidate regardless of whether the client publishes a package schema. Before any automatic install, Darwin must verify a stable client-supported import, update, or API route and record the native asset identity. Until then, the adapter produces a precise human-reviewed update package or instruction set, never claims the client was automatically updated, and accepts only explicit user feedback as behavioral evidence.

## Data and privacy

Adapter data is stored outside the live runtime package. Text evidence remains redacted by default, capped, and locally retained according to Darwin policy. Cross-runtime records contain hashes, metadata, and user-approved evidence references; Darwin does not silently copy an Agent's entire conversation history between products.

## Testing

The core test suite must run without Codex, Claude, WorkBuddy, or Doubao installed. Each adapter provides fixture-based contract tests for discovery, protection, export, candidate packaging, stale-plan rejection, promotion snapshot, and rollback. A real-runtime test is separate and may only claim the adapter capability actually exercised.

For every adapter, the acceptance matrix records whether these capabilities are verified: discovery, manual feedback, import/export, deterministic validation, runtime observation, promotion apply, and rollback. Unsupported capabilities are shown as unavailable, not simulated.

## Success criteria

- The same candidate lifecycle operates on fixture assets from at least three adapter types.
- Codex behavior is preserved and existing v0.2 safeguards remain green.
- Claude, WorkBuddy, and Doubao adapters can each produce a reviewable candidate and promotion plan without assuming undocumented APIs.
- A runtime-specific installer cannot mutate a live asset without the core approval record and adapter target/hash checks.
- Public renaming and release occur only after the first non-Codex adapters have verified their stated capability level.
