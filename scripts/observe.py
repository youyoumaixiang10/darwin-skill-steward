#!/usr/bin/env python3
"""Passive Codex Hook adapter for Darwin."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adapters.codex import CodexAdapter
from telemetry import initialize_data_dir, prune_evidence, record_event, resolve_data_dir


def observe(payload: dict) -> None:
    # Hooks already receive PLUGIN_DATA. Avoid writing a separate locator from
    # the sandboxed Hook process because that path may be intentionally read-only.
    data_dir = initialize_data_dir(resolve_data_dir(), write_locator=False)
    translated = CodexAdapter().translate_hook(payload)
    event_name = str(payload.get("hook_event_name", "Unknown"))
    common = {
        "session_id": payload.get("session_id"),
        "turn_id": payload.get("turn_id"),
        "cwd": payload.get("cwd"),
        "model": payload.get("model"),
        "hook_event_name": event_name,
        "runtime_id": translated.runtime_id,
        "skill_state": translated.skill_state,
    }
    if event_name == "UserPromptSubmit":
        record_event(
            data_dir,
            "prompt_submitted",
            {**common, "outcome": "UNKNOWN", "attribution_source": "UNKNOWN"},
            raw_label="user_prompt",
            raw_text=str(payload.get("prompt", "")),
        )
    elif event_name == "Stop":
        message = payload.get("last_assistant_message")
        record_event(
            data_dir,
            "turn_stopped",
            {**common, "outcome": "UNKNOWN", "attribution_source": "UNKNOWN"},
            raw_label="assistant_message",
            raw_text="" if message is None else str(message),
        )
    elif event_name == "SessionEnd":
        record_event(data_dir, "session_ended", {**common, "reason": payload.get("reason")})
        prune_evidence(data_dir)
    else:
        record_event(data_dir, "hook_observed", common)


def main() -> int:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw or "{}")
        if not isinstance(payload, dict):
            raise ValueError("Hook input must be a JSON object")
        observe(payload)
    except Exception as exc:  # Hooks must never block a Codex turn.
        print(f"Darwin sensor warning: {exc}", file=sys.stderr)
    print("{}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
