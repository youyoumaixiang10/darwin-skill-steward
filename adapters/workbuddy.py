"""WorkBuddy Skill adapter using its documented local ZIP import format."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from darwin_core.adapter import RuntimeAdapter
from darwin_core.models import RuntimeAsset

from ._skill_package import (
    discover_skills,
    manual_apply_plan,
    package_skill_zip,
    read_skill,
    require_frontmatter,
    skill_roots,
    unique_roots,
)


class WorkBuddyAdapter(RuntimeAdapter):
    runtime_id = "workbuddy"

    def __init__(self, home: Path | None = None, cwd: Path | None = None, roots: Iterable[Path] | None = None) -> None:
        self.home = (home or Path.home()).expanduser().resolve()
        self.cwd = (cwd or Path.cwd()).resolve()
        self._explicit_roots = list(roots) if roots is not None else None

    def discovery_roots(self) -> list[Path]:
        if self._explicit_roots is not None:
            return unique_roots(self._explicit_roots)
        return skill_roots(self.home, self.cwd, (".agents", "skills"))

    def discover_assets(self) -> Iterable[RuntimeAsset]:
        return discover_skills(self.runtime_id, self.discovery_roots(), origin="user")

    def read_asset(self, asset: RuntimeAsset) -> str:
        return read_skill(asset)

    def package_candidate(self, asset: RuntimeAsset, destination: str):
        require_frontmatter(asset, ("description", "description_zh", "description_en", "version", "author"))
        return package_skill_zip(asset, destination)

    def prepare_apply(self, plan: dict[str, object]):
        asset = plan["asset"]
        package = plan["package"]
        return manual_apply_plan(
            asset,
            package,
            steps=[
                "Open WorkBuddy and go to Expert, Skill, and Connector management.",
                "Choose Add Skill > Upload Skill and select the reviewed ZIP.",
                "Review the Skill source and permissions before enabling it.",
            ],
            verification="Start a new WorkBuddy task and confirm the Skill appears under Installed Skills.",
        )

    def prepare_rollback(self, plan: dict[str, object]):
        asset = plan["asset"]
        package = plan["package"]
        return manual_apply_plan(
            asset,
            package,
            steps=[
                "Open WorkBuddy's Installed Skills view.",
                "Upload the previously approved Skill ZIP.",
                "Approve replacement only when WorkBuddy shows the expected Skill identity and version.",
            ],
            verification="Start a new task and confirm the previous Skill behavior is restored.",
        )
