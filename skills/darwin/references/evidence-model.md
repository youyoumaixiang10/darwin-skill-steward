# Darwin v0.1 evidence model

## Evidence lanes

| Lane | Examples | What it can prove |
|---|---|---|
| `STRUCTURAL` | file hash, frontmatter, exact duplicate, inferred text overlap | What exists and how similar files appear |
| `BEHAVIORAL` | attributed invocation event | That a named Skill was reported as used, subject to attribution source |
| `HUMAN` | explicit `POSITIVE`, `REFINEMENT`, or `FAILURE` label | The user's stated outcome for a linked event |
| `EXPERIMENTAL` | controlled parent/candidate eval | Comparative performance; not produced by v0.1 |

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
- `MERGE`: structural overlap; exact duplicates are observed, near-duplicates are inferred.
- `ARCHIVE`: complete usage coverage, sustained inactivity, and overlapping or replaced capability. Missing telemetry alone never qualifies.
- `EVOLVE`: repeated explicit failures on an attributed, frequently used Skill. v0.1 stops at the recommendation.
