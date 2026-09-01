#!/usr/bin/env python3
"""Passive Codex Hook adapter for Darwin."""

from __future__ import annotations

import json
import sys

from telemetry import initialize_data_dir, prune_evidence, record_event, resolve_data_dir


def observe(payload: dict) -> None:
    data_dir = initialize_data_dir(resolve_data_dir())
    event_name = str(payload.get("hook_event_name", "Unknown"))
    common = {
        "session_id": payload.get("session_id"),
        "turn_id": payload.get("turn_id"),
        "cwd": payload.get("cwd"),
        "model": payload.get("model"),
        "hook_event_name": event_name,
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
