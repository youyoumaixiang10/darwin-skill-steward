"""Shared helpers for runtimes that import Agent Skills as folders or ZIP files."""

from __future__ import annotations

import hashlib
import json
import os
import zipfile
from pathlib import Path
from typing import Iterable

from darwin_core.frontmatter import FrontmatterResult, parse_frontmatter_file
from darwin_core.models import RuntimeAsset


def unique_roots(candidates: Iterable[Path]) -> list[Path]:
    roots: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate.is_dir():
            continue
        resolved = candidate.expanduser().resolve()
        key = os.path.normcase(str(resolved))
        if key not in seen:
            seen.add(key)
            roots.append(resolved)
    return roots


def skill_roots(home: Path, cwd: Path, relative: tuple[str, ...]) -> list[Path]:
    candidates = [home.joinpath(*relative)]
    try:
        boundary = Path(os.path.commonpath([str(home), str(cwd)])).resolve()
    except ValueError:
        boundary = Path(cwd.anchor).resolve()
    current = cwd
    while True:
        candidates.append(current.joinpath(*relative))
        if current == boundary or current.parent == current:
            break
        current = current.parent
    return unique_roots(candidates)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def discover_skills(runtime_id: str, roots: Iterable[Path], *, origin: str) -> Iterable[RuntimeAsset]:
    seen: set[str] = set()
    for root in roots:
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
                runtime_id=runtime_id,
                native_id=native_id,
                kind="skill",
                path=str(folder),
                origin=origin,
                content_sha256=file_sha256(skill_md),
                metadata={"skill_md": str(skill_md), "discovery_root": str(root)},
            )


def read_skill(asset: RuntimeAsset) -> str:
    skill_md = Path(asset.metadata.get("skill_md", Path(asset.path) / "SKILL.md"))
    return skill_md.read_text(encoding="utf-8", errors="replace")


def frontmatter_fields(asset: RuntimeAsset) -> FrontmatterResult:
    skill_md = Path(asset.metadata.get("skill_md", Path(asset.path) / "SKILL.md"))
    return parse_frontmatter_file(skill_md)


def require_frontmatter(asset: RuntimeAsset, required: Iterable[str]) -> None:
    result = frontmatter_fields(asset)
    required_fields = tuple(dict.fromkeys(("name", "description", *required)))
    missing = [
        name
        for name in required_fields
        if not isinstance(result.fields.get(name), str) or not result.fields[name].strip()
    ]
    if result.parse_errors:
        raise ValueError(f"{asset.runtime_id} package has invalid SKILL.md frontmatter: {'; '.join(result.parse_errors)}")
    if missing:
        raise ValueError(f"{asset.runtime_id} package requires SKILL.md fields: {', '.join(missing)}")


def _safe_files(source: Path) -> Iterable[tuple[Path, Path]]:
    source = source.resolve()
    for path in sorted(source.rglob("*")):
        if not path.is_file() or path.is_symlink() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(source)
        except ValueError as exc:
            raise ValueError(f"Asset file escapes its source folder: {path}") from exc
        yield resolved, relative


def _package_output(source: Path, destination: str, default_name: str) -> Path:
    output = Path(destination).expanduser().resolve()
    if output.suffix.lower() != ".zip":
        output = output / default_name
    if output == source or source in output.parents:
        raise ValueError(f"Package destination must not be inside the Skill being packaged: {source}")
    output.parent.mkdir(parents=True, exist_ok=True)
    return output


def package_skill_zip(asset: RuntimeAsset, destination: str, *, root_name: str | None = None) -> dict[str, str]:
    source = Path(asset.path).resolve()
    if not (source / "SKILL.md").is_file():
        raise ValueError(f"Skill has no SKILL.md: {source}")
    output = _package_output(source, destination, f"{source.name}.zip")
    prefix = root_name or source.name
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, relative in _safe_files(source):
            archive.write(path, (Path(prefix) / relative).as_posix())
    return {
        "runtime_id": asset.runtime_id,
        "native_id": asset.native_id,
        "package_path": str(output),
        "sha256": file_sha256(output),
        "format": "agent-skill-zip",
    }


def package_claude_plugin(asset: RuntimeAsset, destination: str, *, surface: str) -> dict[str, str]:
    source = Path(asset.path).resolve()
    if not (source / "SKILL.md").is_file():
        raise ValueError(f"Skill has no SKILL.md: {source}")
    output = _package_output(source, destination, f"darwin-{source.name}-{surface}.zip")
    manifest = {
        "name": f"darwin-{source.name}",
        "version": "0.1.0",
        "description": f"Darwin-managed candidate for {source.name}",
    }
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(".claude-plugin/plugin.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        for path, relative in _safe_files(source):
            archive.write(path, (Path("skills") / source.name / relative).as_posix())
    return {
        "runtime_id": asset.runtime_id,
        "native_id": asset.native_id,
        "package_path": str(output),
        "sha256": file_sha256(output),
        "format": "claude-plugin-zip",
        "surface": surface,
    }


def manual_apply_plan(asset: RuntimeAsset, package: dict[str, str], *, steps: list[str], verification: str) -> dict[str, object]:
    return {
        "runtime_id": asset.runtime_id,
        "native_id": asset.native_id,
        "mode": "manual_import",
        "package_path": package["package_path"],
        "package_sha256": package["sha256"],
        "steps": steps,
        "verification": verification,
        "automatic_apply": False,
    }
