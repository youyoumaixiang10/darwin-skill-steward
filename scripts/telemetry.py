#!/usr/bin/env python3
"""Local telemetry storage for Darwin for Codex v0.1.

The module deliberately separates event metadata from short-lived text evidence.
It uses only the Python standard library so Hook execution has no package setup.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import uuid
from typing import Any, Iterable


SCHEMA_VERSION = 1
PLUGIN_ID = "darwin-for-codex"
OUTCOMES = {"POSITIVE", "REFINEMENT", "FAILURE", "UNKNOWN"}
ATTRIBUTION_SOURCES = {
    "PLATFORM",
    "MANAGED_SELF_REPORT",
    "MANUAL",
    "INFERRED",
    "UNKNOWN",
}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def parse_time(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def resolve_data_dir(explicit: str | os.PathLike[str] | None = None) -> Path:
    """Resolve runtime storage without assuming a documented PLUGIN_DATA layout."""
    if explicit:
        return Path(explicit).expanduser().resolve()
    for key in ("DARWIN_DATA_DIR", "PLUGIN_DATA"):
        if os.environ.get(key):
            return Path(os.environ[key]).expanduser().resolve()

    locator = Path.home() / ".codex" / PLUGIN_ID / "data-location.json"
    if locator.is_file():
        try:
            candidate = Path(json.loads(locator.read_text(encoding="utf-8"))["data_dir"])
            if candidate.is_dir():
                return candidate.resolve()
        except (OSError, ValueError, KeyError, TypeError):
            pass
    return (Path.home() / ".codex" / PLUGIN_ID / "data").resolve()


def initialize_data_dir(data_dir: Path, write_locator: bool = True) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    for relative in (
        "evidence/raw",
        "evidence/spool",
        "evolution",
        "archive",
        "approvals",
    ):
        (data_dir / relative).mkdir(parents=True, exist_ok=True)

    if write_locator and os.environ.get("PLUGIN_DATA"):
        locator = Path.home() / ".codex" / PLUGIN_ID / "data-location.json"
        try:
            atomic_write_json(locator, {"schema_version": 1, "data_dir": str(data_dir)})
        except OSError:
            # The Hook can still use PLUGIN_DATA even if a later manual CLI needs --data-dir.
            pass
    return data_dir


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temp_name)


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError, TypeError):
        return default


@contextlib.contextmanager
def exclusive_lock(path: Path, timeout: float = 1.0) -> Iterable[bool]:
    deadline = time.monotonic() + timeout
    acquired = False
    while time.monotonic() < deadline:
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            acquired = True
            break
        except (FileExistsError, PermissionError):
            time.sleep(0.025)
    try:
        yield acquired
    finally:
        if acquired:
            with contextlib.suppress(FileNotFoundError):
                path.unlink()


def append_event(data_dir: Path, event: dict[str, Any]) -> str:
    initialize_data_dir(data_dir)
    event.setdefault("schema_version", SCHEMA_VERSION)
    event.setdefault("event_id", str(uuid.uuid4()))
    event.setdefault("timestamp", utc_now())
    line = json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
    event_path = data_dir / "events.jsonl"
    with exclusive_lock(data_dir / ".events.lock") as acquired:
        if acquired:
            with event_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
        else:
            # Never corrupt or silently discard evidence when concurrent Hooks contend.
            spool = data_dir / "evidence" / "spool" / f"{event['event_id']}.json"
            atomic_write_json(spool, event)
    return str(event["event_id"])


def iter_events(data_dir: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    path = data_dir / "events.jsonl"
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                item = json.loads(line)
                if isinstance(item, dict):
                    events.append(item)
            except ValueError:
                continue
    spool = data_dir / "evidence" / "spool"
    if spool.is_dir():
        for path in spool.glob("*.json"):
            item = load_json(path, None)
            if isinstance(item, dict):
                events.append(item)
    return sorted(events, key=lambda item: (item.get("timestamp", ""), item.get("event_id", "")))


SECRET_PATTERNS = (
    (re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"), "[REDACTED_API_KEY]"),
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{12,}=*"), "Bearer [REDACTED_TOKEN]"),
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[REDACTED_EMAIL]"),
)


def redact_text(value: str) -> str:
    result = value
    for pattern, replacement in SECRET_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


def default_config() -> dict[str, Any]:
    return {
        "raw_evidence_retention_days": 30,
        "capture_mode": "redacted",
        "max_evidence_chars": 4000,
    }


def load_runtime_config(data_dir: Path) -> dict[str, Any]:
    config = default_config()
    config.update(load_json(data_dir / "config.json", {}))
    if os.environ.get("DARWIN_CAPTURE_MODE"):
        config["capture_mode"] = os.environ["DARWIN_CAPTURE_MODE"].lower()
    return config


def store_evidence(data_dir: Path, event_id: str, label: str, text: str) -> str | None:
    config = load_runtime_config(data_dir)
    mode = str(config.get("capture_mode", "redacted")).lower()
    if mode == "off":
        return None
    limit = max(0, int(config.get("max_evidence_chars", 4000)))
    stored = text if mode == "full" else redact_text(text)
    stored = stored[:limit]
    retention = max(0, int(config.get("raw_evidence_retention_days", 30)))
    now = dt.datetime.now(dt.timezone.utc)
    relative = Path("evidence") / "raw" / now.date().isoformat() / f"{event_id}.json"
    atomic_write_json(
        data_dir / relative,
        {
            "schema_version": SCHEMA_VERSION,
            "event_id": event_id,
            "label": label,
            "capture_mode": mode,
            "text": stored,
            "truncated": len(text) > limit,
            "created_at": now.isoformat().replace("+00:00", "Z"),
            "expires_at": (now + dt.timedelta(days=retention)).isoformat().replace("+00:00", "Z"),
        },
    )
    return relative.as_posix()


def record_event(
    data_dir: Path,
    event_type: str,
    fields: dict[str, Any] | None = None,
    raw_label: str | None = None,
    raw_text: str | None = None,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "event_id": str(uuid.uuid4()),
        "timestamp": utc_now(),
        "event_type": event_type,
    }
    if fields:
        event.update({key: value for key, value in fields.items() if value is not None})
    if raw_text is not None:
        event["content_sha256"] = sha256_text(raw_text)
        event["content_length"] = len(raw_text)
        reference = store_evidence(data_dir, event["event_id"], raw_label or event_type, raw_text)
        if reference:
            event["evidence_ref"] = reference
    append_event(data_dir, event)
    return event


def prune_evidence(data_dir: Path, now: dt.datetime | None = None) -> int:
    now = now or dt.datetime.now(dt.timezone.utc)
    removed = 0
    root = data_dir / "evidence" / "raw"
    if not root.is_dir():
        return 0
    for path in root.rglob("*.json"):
        value = load_json(path, {})
        expires = value.get("expires_at")
        if expires:
            with contextlib.suppress(ValueError):
                if parse_time(expires) <= now:
                    path.unlink()
                    removed += 1
    return removed


def attribution_status(source: str) -> str:
    return {
        "PLATFORM": "OBSERVED",
        "MANAGED_SELF_REPORT": "OBSERVED",
        "MANUAL": "EXPLICIT",
        "INFERRED": "INFERRED",
        "UNKNOWN": "UNKNOWN",
    }[source]


def print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Darwin local telemetry")
    parser.add_argument("--data-dir", help="Override PLUGIN_DATA for development or tests")
    sub = parser.add_subparsers(dest="command", required=True)

    invocation = sub.add_parser("record-invocation", help="Record an attributed Skill invocation")
    invocation.add_argument("--skill", required=True)
    invocation.add_argument("--record-id", help="Registry record id; required when Skill names collide")
    invocation.add_argument("--turn-id", required=True)
    invocation.add_argument("--session-id")
    invocation.add_argument("--skill-version")
    invocation.add_argument("--source", choices=sorted(ATTRIBUTION_SOURCES), required=True)

    outcome = sub.add_parser("record-outcome", help="Record an explicit outcome")
    outcome.add_argument("--skill", required=True)
    outcome.add_argument("--record-id", help="Registry record id; required when Skill names collide")
    outcome.add_argument("--turn-id", required=True)
    outcome.add_argument("--outcome", choices=sorted(OUTCOMES), required=True)
    outcome.add_argument("--reason")
    outcome.add_argument("--failure-tag")

    coverage = sub.add_parser("record-coverage", help="Declare observability coverage")
    coverage.add_argument("--skill", required=True)
    coverage.add_argument("--record-id", help="Registry record id; required when Skill names collide")
    coverage.add_argument("--level", choices=("NONE", "PARTIAL", "COMPLETE"), required=True)
    coverage.add_argument("--source", required=True, help="Why this coverage claim is valid")
    coverage.add_argument("--since", help="ISO-8601 start of the claimed coverage window")

    sub.add_parser("summary", help="Summarize event counts without treating UNKNOWN as success")
    sub.add_parser("prune", help="Delete expired short-term text evidence")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    data_dir = initialize_data_dir(resolve_data_dir(args.data_dir), write_locator=not bool(args.data_dir))

    if args.command == "record-invocation":
        event = record_event(
            data_dir,
            "skill_invocation",
            {
                "skill_id": args.skill,
                "record_id": args.record_id,
                "turn_id": args.turn_id,
                "session_id": args.session_id,
                "skill_version": args.skill_version,
                "attribution_source": args.source,
                "attribution_status": attribution_status(args.source),
                "outcome": "UNKNOWN",
            },
        )
        print_json(event)
        return 0

    if args.command == "record-outcome":
        event = record_event(
            data_dir,
            "outcome",
            {
                "skill_id": args.skill,
                "record_id": args.record_id,
                "turn_id": args.turn_id,
                "outcome": args.outcome,
                "outcome_status": "EXPLICIT" if args.outcome != "UNKNOWN" else "UNKNOWN",
                "reason": args.reason,
                "failure_tag": args.failure_tag,
            },
        )
        print_json(event)
        return 0

    if args.command == "record-coverage":
        if args.level == "COMPLETE" and not args.since:
            raise SystemExit("COMPLETE coverage requires --since; declaration time is not historical coverage.")
        if args.since:
            try:
                parse_time(args.since)
            except ValueError as exc:
                raise SystemExit(f"Invalid --since timestamp: {args.since}") from exc
        event = record_event(
            data_dir,
            "coverage_declared",
            {
                "skill_id": args.skill,
                "record_id": args.record_id,
                "coverage": args.level,
                "coverage_source": args.source,
                "coverage_since": args.since,
                "evidence_lane": "HUMAN",
                "evidence_status": "EXPLICIT",
            },
        )
        print_json(event)
        return 0

    if args.command == "prune":
        print_json({"removed": prune_evidence(data_dir), "data_dir": str(data_dir)})
        return 0

    events = iter_events(data_dir)
    counts: dict[str, int] = {}
    outcomes = {name: 0 for name in sorted(OUTCOMES)}
    for event in events:
        event_type = str(event.get("event_type", "unknown"))
        counts[event_type] = counts.get(event_type, 0) + 1
        outcome = event.get("outcome")
        if outcome in outcomes:
            outcomes[str(outcome)] += 1
    print_json(
        {
            "data_dir": str(data_dir),
            "events": len(events),
            "event_types": counts,
            "outcomes": outcomes,
            "note": "UNKNOWN is reported separately and is never counted as POSITIVE.",
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
