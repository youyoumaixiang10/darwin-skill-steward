"""Codex runtime adapter for local Skill discovery and hook translation."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Iterable

from darwin_core.adapter import RuntimeAdapter
from darwin_core.models import RuntimeAsset, RuntimeObservation


class CodexAdapter(RuntimeAdapter):
    runtime_id = "codex"

    def __init__(self, home: Path | None = None, cwd: Path | None = None, include_plugin_cache: bool = True) -> None:
        self.home = (home or Path.home()).expanduser().resolve()
        self.cwd = (cwd or Path.cwd()).resolve()
        self.include_plugin_cache = include_plugin_cache

    def _roots(self) -> list[Path]:
        candidates = [self.home / ".codex" / "skills", self.home / ".agents" / "skills"]
        current = self.cwd
        while True:
            candidates.append(current / ".agents" / "skills")
            if current.parent == current:
                break
            current = current.parent
        if self.include_plugin_cache:
            candidates.append(self.home / ".codex" / "plugins" / "cache")
        roots: list[Path] = []
        seen: set[str] = set()
        for candidate in candidates:
            if not candidate.is_dir():
                continue
            value = candidate.resolve()
            key = os.path.normcase(str(value))
            if key not in seen:
                seen.add(key)
                roots.append(value)
        return roots

    def discovery_roots(self) -> list[Path]:
        return self._roots()

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _origin(folder: Path) -> str:
        parts = {part.lower() for part in folder.parts}
        if ".system" in parts:
            return "system"
        if "plugins" in parts and "cache" in parts:
            return "plugin"
        if ".agents" in parts:
            return "repository"
        return "user"

    def discover_assets(self) -> Iterable[RuntimeAsset]:
        seen: set[str] = set()
        for root in self._roots():
            for skill_md in root.rglob("SKILL.md"):
                if not skill_md.is_file() or skill_md.is_symlink():
                    continue
                folder = skill_md.parent.resolve()
                key = os.path.normcase(str(folder))
                if key in seen:
                    continue
                seen.add(key)
                try:
                    native_id = folder.relative_to(root).as_posix()
                except ValueError:
                    native_id = folder.name
                yield RuntimeAsset(
                    runtime_id=self.runtime_id,
                    native_id=native_id,
                    kind="skill",
                    path=str(folder),
                    origin=self._origin(folder),
                    content_sha256=self._sha256(skill_md),
                    metadata={"skill_md": str(skill_md.resolve())},
                )

    def read_asset(self, asset: RuntimeAsset) -> str:
        skill_md = Path(asset.metadata.get("skill_md", Path(asset.path) / "SKILL.md"))
        return skill_md.read_text(encoding="utf-8", errors="replace")

    def translate_hook(self, payload: dict[str, object]) -> RuntimeObservation:
        event = str(payload.get("hook_event_name", "unknown"))
        kinds = {"UserPromptSubmit": "prompt_submitted", "Stop": "turn_finished", "SessionEnd": "session_finished"}
        return RuntimeObservation(
            runtime_id=self.runtime_id,
            kind=kinds.get(event, "runtime_event"),
            skill_state="UNKNOWN",
            fields={"source_event": event},
        )




