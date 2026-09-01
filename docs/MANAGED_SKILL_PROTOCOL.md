# Managed Skill telemetry protocol v0.1

Darwin does not patch existing Skills automatically.

A Darwin-aware adapter may report an invocation only when it can supply the actual Skill id and Codex turn id:

```text
python scripts/telemetry.py record-invocation \
  --skill xhs-title \
  --record-id <registry-record-id> \
  --turn-id <actual-turn-id> \
  --source MANAGED_SELF_REPORT
```

If the adapter cannot obtain the actual turn id, it must use `INFERRED` or `UNKNOWN`; it must not invent an id or label the record `MANAGED_SELF_REPORT`.

`record-id` is strongly recommended and is mandatory when more than one installed Skill has the same `name`. Name-only events are excluded for ambiguous names so evidence cannot leak across Skills.

Explicit user outcomes are recorded separately:

```text
python scripts/telemetry.py record-outcome \
  --skill xhs-title \
  --turn-id <same-turn-id> \
  --outcome FAILURE \
  --failure-tag repetitive-pattern \
  --reason "User explicitly rejected the repeated title pattern"
```

The health engine counts an outcome only when it links to an attributed invocation for the same Skill and turn.

Complete coverage is a historical claim and must include its real start time:

```text
python scripts/telemetry.py record-coverage \
  --skill xhs-title \
  --record-id <registry-record-id> \
  --level COMPLETE \
  --since 2026-09-01T00:00:00Z \
  --source "Verified platform export covers every invocation since this time"
```
