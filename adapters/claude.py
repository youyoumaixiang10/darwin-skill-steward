"""Claude Code and Claude Cowork adapters."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from darwin_core.adapter import RuntimeAdapter
from darwin_core.models import RuntimeAsset, RuntimeObservation

from ._skill_package import discover_skills, manual_apply_plan, package_claude_plugin, read_skill, skill_roots, unique_roots


class ClaudeCodeAdapter(RuntimeAdapter):
    runtime_id = "claude_code"

    def __init__(self, home: Path | None = None, cwd: Path | None = None, roots: Iterable[Path] | None = None) -> None:
        self.home = (home or Path.home()).expanduser().resolve()
        self.cwd = (cwd or Path.cwd()).resolve()
        self._explicit_roots = list(roots) if roots is not None else None

    def discovery_roots(self) -> list[Path]:
        if self._explicit_roots is not None:
            return unique_roots(self._explicit_roots)
        return skill_roots(self.home, self.cwd, (".claude", "skills"))

    def discover_assets(self) -> Iterable[RuntimeAsset]:
        return discover_skills(self.runtime_id, self.discovery_roots(), origin="user")

    def read_asset(self, asset: RuntimeAsset) -> str:
        return read_skill(asset)

    def package_candidate(self, asset: RuntimeAsset, destination: str):
        return package_claude_plugin(asset, destination, surface="code")

    def prepare_apply(self, plan: dict[str, object]):
        asset = plan["asset"]
        package = plan["package"]
        return manual_apply_plan(
            asset,
            package,
            steps=[
                "Unpack the reviewed plugin ZIP.",
                "Run Claude Code with --plugin-dir pointing to the unpacked plugin for verification.",
                "Install it through a trusted Claude plugin marketplace only after verification.",
            ],
            verification="Start a new Claude Code session and confirm the namespaced Skill is available.",
        )

    def prepare_rollback(self, plan: dict[str, object]):
        asset = plan["asset"]
        package = plan["package"]
        return manual_apply_plan(
            asset,
            package,
            steps=[
                "Unpack the previously approved Claude plugin snapshot.",
                "Verify it with --plugin-dir in a new Claude Code session.",
                "Reinstall that reviewed snapshot through the same trusted marketplace path.",
            ],
            verification="Confirm the previous namespaced Skill version is active in a new Claude Code session.",
        )

    def translate_hook(self, payload: dict[str, object]) -> RuntimeObservation:
        event = str(payload.get("hook_event_name", "unknown"))
        kinds = {"UserPromptSubmit": "prompt_submitted", "Stop": "turn_finished", "SessionEnd": "session_finished"}
        return RuntimeObservation(
            runtime_id=self.runtime_id,
            kind=kinds.get(event, "runtime_event"),
            skill_state="UNKNOWN",
            fields={"source_event": event},
        )

    def observe(self, payload: dict[str, object]):
        return self.translate_hook(payload)


class ClaudeCoworkAdapter(RuntimeAdapter):
    runtime_id = "claude_cowork"

    def __init__(self, roots: Iterable[Path] | None = None) -> None:
        self.roots = unique_roots(roots or [])

    def discover_assets(self) -> Iterable[RuntimeAsset]:
        return discover_skills(self.runtime_id, self.roots, origin="export")

    def read_asset(self, asset: RuntimeAsset) -> str:
        return read_skill(asset)

    def package_candidate(self, asset: RuntimeAsset, destination: str):
        return package_claude_plugin(asset, destination, surface="cowork")

    def prepare_apply(self, plan: dict[str, object]):
        asset = plan["asset"]
        package = plan["package"]
        return manual_apply_plan(
            asset,
            package,
            steps=[
                "Open Claude Cowork and go to Customize > Plugins.",
                "Upload the reviewed custom plugin ZIP.",
                "Review the plugin's Skills, hooks, connectors, and requested permissions before enabling it.",
            ],
            verification="Open a new Cowork task and confirm the Skill appears in the plugin's details and Skill picker.",
        )

    def prepare_rollback(self, plan: dict[str, object]):
        asset = plan["asset"]
        package = plan["package"]
        return manual_apply_plan(
            asset,
            package,
            steps=[
                "Open Claude Cowork and review the previously approved plugin snapshot.",
                "Upload that snapshot through Customize > Plugins.",
                "Approve replacement only when the displayed plugin identity matches the rollback target.",
            ],
            verification="Open a new Cowork task and confirm the previous Skill behavior is restored.",
        )
