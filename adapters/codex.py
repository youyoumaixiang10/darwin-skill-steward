"""Codex runtime adapter for local Skill discovery and hook translation."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Iterable

from darwin_core.adapter import RuntimeAdapter
from darwin_core.models import RuntimeAsset, RuntimeObservation


OFFICIAL_PLUGIN_PUBLISHERS = {
    "openai-bundled",
    "openai-curated",
    "openai-curated-remote",
    "openai-primary-runtime",
}


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _load_manifest(version_root: Path) -> dict[str, object]:
    for candidate in (version_root / ".codex-plugin" / "plugin.json", version_root / "plugin.json"):
        try:
            loaded = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if isinstance(loaded, dict):
            return loaded
    return {}


def _active_plugin_version(plugin_root: Path) -> tuple[str | None, str]:
    latest = plugin_root / "latest"
    is_junction = getattr(latest, "is_junction", lambda: False)
    if latest.is_symlink() or is_junction():
        try:
            resolved = latest.resolve(strict=True)
            if resolved.parent == plugin_root.resolve() and resolved.name != "latest":
                return resolved.name, "latest_link"
        except OSError:
            pass
    registration_path = plugin_root / ".codex-remote-plugin-install.json"
    try:
        registration = json.loads(registration_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        registration = {}
    if isinstance(registration, dict):
        for key in ("active_version", "selected_version", "installed_version", "version"):
            value = registration.get(key)
            if isinstance(value, str) and (plugin_root / value).is_dir():
                return value, f"install_registration:{key}"
    return None, "unresolved"


def classify_location(
    folder: Path,
    discovery_root: Path,
    *,
    home: Path,
    cwd: Path,
) -> dict[str, object]:
    folder = folder.resolve()
    discovery_root = discovery_root.resolve()
    home = home.resolve()
    cwd = cwd.resolve()
    lower_parts = {part.lower() for part in folder.parts}
    if ".system" in lower_parts:
        return {
            "origin": "SYSTEM",
            "scope": "system",
            "runtime_id": "codex",
            "deployment_id": "codex_system",
            "runtime_targets": ["codex"],
            "manageable": False,
            "protection_reason": "System Skill",
            "asset_state": "ACTIVE_RUNTIME_ASSET",
        }

    plugin_cache = home / ".codex" / "plugins" / "cache"
    if _is_relative_to(folder, plugin_cache):
        relative = folder.relative_to(plugin_cache)
        parts = relative.parts
        publisher = parts[0] if parts else "unknown"
        plugin_name = parts[1] if len(parts) > 1 else "unknown"
        version_directory = parts[2] if len(parts) > 2 else None
        plugin_root = plugin_cache / publisher / plugin_name
        version_root = plugin_root / version_directory if version_directory else plugin_root
        manifest = _load_manifest(version_root)
        manifest_version = manifest.get("version")
        plugin_version = manifest_version if isinstance(manifest_version, str) else version_directory
        official = publisher.lower() in OFFICIAL_PLUGIN_PUBLISHERS
        active_directory, active_basis = _active_plugin_version(plugin_root)
        if active_directory is None:
            asset_state = "CACHED_VERSION_UNKNOWN"
        elif version_directory == active_directory:
            asset_state = "ACTIVE_PLUGIN_ASSET"
        else:
            asset_state = "INACTIVE_CACHED_VERSION"
        return {
            "origin": "OFFICIAL_PLUGIN" if official else "THIRD_PARTY_PLUGIN",
            "scope": "plugin",
            "runtime_id": "codex",
            "deployment_id": f"plugin:{publisher}/{plugin_name}",
            "runtime_targets": ["codex"],
            "manageable": False,
            "protection_reason": "Plugin-bundled Skill",
            "asset_state": asset_state,
            "plugin_publisher": publisher,
            "plugin_id": str(manifest.get("name") or plugin_name),
            "plugin_version": plugin_version,
            "plugin_active_basis": active_basis,
        }

    codex_user = home / ".codex" / "skills"
    agents_user = home / ".agents" / "skills"
    if discovery_root == codex_user or _is_relative_to(folder, codex_user):
        origin, scope, deployment_id = "CODEX_USER", "user", "codex_user"
        runtime_targets = ["codex"]
    elif discovery_root == agents_user or _is_relative_to(folder, agents_user):
        origin, scope, deployment_id = "SHARED_USER", "user", "agents_shared"
        runtime_targets = ["codex", "workbuddy"]
    elif ".agents" in {part.lower() for part in discovery_root.parts}:
        origin, scope, deployment_id = "PROJECT", "project", f"agents_project:{discovery_root}"
        runtime_targets = ["codex", "workbuddy"]
    else:
        origin, scope, deployment_id = "CODEX_USER", "user", f"codex_explicit:{discovery_root}"
        runtime_targets = ["codex"]
    return {
        "origin": origin,
        "scope": scope,
        "runtime_id": "codex",
        "deployment_id": deployment_id,
        "runtime_targets": runtime_targets,
        "manageable": True,
        "protection_reason": None,
        "asset_state": "ACTIVE_RUNTIME_ASSET",
    }


class CodexAdapter(RuntimeAdapter):
    runtime_id = "codex"

    def __init__(self, home: Path | None = None, cwd: Path | None = None, include_plugin_cache: bool = True) -> None:
        self.home = (home or Path.home()).expanduser().resolve()
        self.cwd = (cwd or Path.cwd()).resolve()
        self.include_plugin_cache = include_plugin_cache

    def _roots(self) -> list[Path]:
        candidates = [self.home / ".codex" / "skills", self.home / ".agents" / "skills"]
        try:
            boundary = Path(os.path.commonpath([str(self.home), str(self.cwd)])).resolve()
        except ValueError:
            boundary = Path(self.cwd.anchor).resolve()
        current = self.cwd
        while True:
            candidates.append(current / ".agents" / "skills")
            if current == boundary or current.parent == current:
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
                classification = classify_location(
                    folder,
                    root,
                    home=self.home,
                    cwd=self.cwd,
                )
                yield RuntimeAsset(
                    runtime_id=self.runtime_id,
                    native_id=native_id,
                    kind="skill",
                    path=str(folder),
                    origin=str(classification["origin"]),
                    content_sha256=self._sha256(skill_md),
                    metadata={
                        "skill_md": str(skill_md.resolve()),
                        "discovery_root": str(root),
                        **{
                            key: value
                            for key, value in classification.items()
                            if key not in {"origin", "manageable", "protection_reason"}
                        },
                    },
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




