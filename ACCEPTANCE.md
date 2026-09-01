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
- duplicate and behavior recommendations preserve evidence lanes;
- missing telemetry alone cannot produce `ARCHIVE`;
- archive execution fails without exact approval;
- changed targets invalidate approval;
- archive is reversible;
- no permanent delete command exists;
- manifest, Hook configuration, scripts, Schema files, and docs are present.

## Manual plugin acceptance

1. Add the plugin to a local marketplace and install it.
2. Start a new Codex task; plugins are picked up in new tasks.
3. Open `/hooks`, review the exact Darwin Hook definitions, and trust them.
4. Submit one prompt and let one turn stop.
5. Run `telemetry.py summary`; confirm prompt/stop events exist and outcomes show `UNKNOWN`.
6. Run `registry.py scan`, then `health.py report --format markdown`.
7. Confirm official/system Skills show protected `KEEP`, and the report states that first-run usage is unknown.
8. On a disposable user Skill, run `archive.py plan`. Confirm nothing moves before the exact approval phrase is returned.
9. Approve, archive, create a restore plan, approve again, and confirm the original tree hash is restored.

Passing local unit tests proves structure and deterministic safeguards. It does not prove Hook trust UI behavior or real Skill invocation attribution; those require the manual new-task test above.
