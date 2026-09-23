# Darwin evidence model

## Evidence lanes

| Lane | Examples | What it can prove |
|---|---|---|
| `STRUCTURAL` | parsed frontmatter, Skill file hash, complete tree hash, inferred text overlap | What exists and which level of similarity is actually established |
| `BEHAVIORAL` | attributed invocation event | That a named Skill was reported as used, subject to attribution source |
| `HUMAN` | explicit `POSITIVE`, `REFINEMENT`, or `FAILURE` label | The user's stated outcome for a linked event |
| `EXPERIMENTAL` | controlled parent/candidate eval | Comparative performance from isolated Darwin evaluations |

Evidence status is one of `OBSERVED`, `INFERRED`, `EXPLICIT`, or `UNKNOWN`. Do not collapse the lanes into a single numeric confidence score.

## Attribution

`PLATFORM` and `MANAGED_SELF_REPORT` may support high-confidence usage counts. `MANUAL` is explicit but depends on the user's identification. `INFERRED` is useful for triage but not for high-confidence evolution metrics. `UNKNOWN` is excluded.

## Outcomes

- `POSITIVE`: the user explicitly accepts or approves the result.
- `REFINEMENT`: the direction is acceptable and the user requests normal iteration.
- `FAILURE`: the user explicitly rejects, corrects, or restarts because the result is wrong or unusable.
- `UNKNOWN`: no explicit outcome is available.

The `Stop` Hook always creates `UNKNOWN`; it only proves that Codex stopped the turn.

## Recommendation gates

- `KEEP`: sufficient known outcomes and a low failure rate.
- `OBSERVE`: insufficient, unattributed, or conflicting evidence.
- `MERGE`: complete `SAME_TREE` duplicate within one runtime, after unique files and scripts are compared and a human confirms consolidation.
- `OBSERVE`: `SAME_SKILL_MD`, `SIMILAR_INSTRUCTIONS`, and `CROSS_RUNTIME_MIRROR` findings remain here until stronger evidence exists.
- `ARCHIVE`: complete usage coverage, sustained inactivity, a viable replacement, a complete tree fingerprint, and explicit confirmation that the target runtime no longer needs this copy. Missing telemetry alone never qualifies.
- `EVOLVE`: repeated explicit failures on an attributed, frequently used Skill. Promotion still requires isolated evaluation and explicit approval.
