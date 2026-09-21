"""Doubao client adapter for exported Skills and reviewed manual import."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from darwin_core.adapter import RuntimeAdapter
from darwin_core.models import RuntimeAsset

from ._skill_package import discover_skills, manual_apply_plan, package_skill_zip, read_skill, unique_roots


class DoubaoAdapter(RuntimeAdapter):
    runtime_id = "doubao_client"

    def __init__(self, roots: Iterable[Path] | None = None) -> None:
        # Only scan folders the user explicitly exported or selected because
        # Doubao does not document a stable local installed-Skill directory.
        self.roots = unique_roots(roots or [])

    def discover_assets(self) -> Iterable[RuntimeAsset]:
        return discover_skills(self.runtime_id, self.roots, origin="export")

    def read_asset(self, asset: RuntimeAsset) -> str:
        return read_skill(asset)

    def package_candidate(self, asset: RuntimeAsset, destination: str):
        artifact = package_skill_zip(asset, destination)
        artifact["compatibility"] = "manual-client-import"
        return artifact

    def prepare_apply(self, plan: dict[str, object]):
        asset = plan["asset"]
        package = plan["package"]
        result = manual_apply_plan(
            asset,
            package,
            steps=[
                "Open the Doubao desktop client's Skill, Connector, and Partner area.",
                "Choose Upload Skill and select the reviewed folder or ZIP package.",
                "Review the generated Skill and approve replacement only if the client shows the expected native Skill.",
            ],
            verification="Create a new Doubao work task, select the imported Skill, and record explicit user feedback in Darwin.",
        )
        result["public_automatic_install_api"] = False
        result["runtime_observation"] = "UNAVAILABLE"
        return result

    def prepare_rollback(self, plan: dict[str, object]):
        asset = plan["asset"]
        package = plan["package"]
        result = manual_apply_plan(
            asset,
            package,
            steps=[
                "Open the Doubao desktop client's Skill management area.",
                "Upload the previously approved Skill snapshot.",
                "Approve replacement only when the client displays the expected rollback target.",
            ],
            verification="Create a new work task, select the restored Skill, and record explicit user verification.",
        )
        result["public_automatic_install_api"] = False
        result["runtime_observation"] = "UNAVAILABLE"
        return result
