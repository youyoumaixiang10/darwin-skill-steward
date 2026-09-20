"""Canonical runtime models shared by Darwin adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RuntimeAsset:
    runtime_id: str
    native_id: str
    kind: str
    path: str
    origin: str = "user"
    content_sha256: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RuntimeObservation:
    runtime_id: str
    kind: str
    skill_state: str = "UNKNOWN"
    fields: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CapabilityUnavailable:
    capability: str
    reason: str
