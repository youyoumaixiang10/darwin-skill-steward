# Darwin for Codex v0.2 Controlled Evolution Design

## Goal

Complete the missing half of Darwin: turn explicit, attributable feedback into an isolated Skill candidate, require real old-versus-new validation, and promote the candidate only after exact human approval.

## Boundary

Darwin may prepare, inspect, and evaluate a candidate automatically. It must never edit a live Skill while preparing a candidate. System, official, plugin-bundled, symlinked, and out-of-root Skills remain protected. UNKNOWN or inferred feedback cannot open a candidate. A dry run or judge score alone cannot authorize promotion.

## Lifecycle

1. `prepare`: select one manageable Skill with an explicit human reason; copy it into `PLUGIN_DATA/evolution/<candidate-id>/candidate`.
2. The agent edits only the candidate copy and uses `record-proposal` to record the proposed change in its manifest.
3. `record-eval`: store evaluation results. Supported modes are `deterministic`, `full_test`, `paired`, and `dry_run`.
4. `plan-promote`: require at least one passing deterministic check, one `full_test` verdict of `BETTER`, and a strict `BETTER` majority from at least three paired judges. Any deterministic failure or `full_test=WORSE` blocks promotion.
5. Generate a unified review diff. Show the proposal, diff path and hash, source and candidate hashes, evidence summary, backup path, expiry, and exact approval phrase.
6. `execute-promote`: recheck every hash and gate, snapshot the source, then replace it only after the exact approval phrase.
7. `plan-rollback` and `rollback`: restore the snapshot through a separate exact approval.

## Evidence rules

- Candidate creation accepts an explicit human reason. Linked FAILURE or REFINEMENT outcomes can support the diagnosis but cannot replace the reason.
- Ordinary prompts, silence, task completion, inferred use, and UNKNOWN outcomes are not improvement evidence.
- Training prompts used to propose changes must not count as validation.
- Evaluation records identify mode, verdict, evaluator, prompt id, evidence note, source hash, and the exact candidate hash tested.
- Multiple feedback items may inform a candidate, but each candidate targets exactly one Skill and one source hash.

## Failure handling

- Source changes after candidate preparation invalidate promotion.
- Candidate changes after approval invalidate approval.
- Missing, changed, or conflicting evaluation evidence blocks the plan.
- Promotion keeps a full source snapshot and never deletes it.
- Failed filesystem replacement restores the source snapshot before returning an error.
- Repeated marginal or tied results remain candidates; they are not promoted.

## Acceptance

- A protected Skill cannot become a candidate.
- Preparing a candidate leaves the source byte-for-byte unchanged.
- Dry-run and paired scores without a real full test cannot pass the gate.
- Three paired evaluations require a strict majority for `BETTER`.
- Incorrect, expired, consumed, or stale approval cannot promote.
- Approved promotion changes only the selected source and creates a restorable snapshot.
- Rollback requires a separate approval and restores the original tree hash.
