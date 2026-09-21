"""Shared, safe YAML frontmatter parsing for Skill packages."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

try:
    import yaml
except ImportError:  # pragma: no cover - exercised only in an incomplete installation
    yaml = None


@dataclass(frozen=True)
class FrontmatterResult:
    fields: dict[str, Any]
    status: str
    missing_required_fields: tuple[str, ...]
    parse_errors: tuple[str, ...]
    structural_valid: bool

    def as_record_fields(self) -> dict[str, Any]:
        return {
            "frontmatter_status": self.status,
            "missing_required_fields": list(self.missing_required_fields),
            "parse_errors": list(self.parse_errors),
            "structural_valid": self.structural_valid,
        }


def parse_frontmatter_text(
    text: str, required: Iterable[str] = ("name", "description")
) -> FrontmatterResult:
    required_fields = tuple(required)
    lines = text.lstrip("\ufeff").splitlines()
    if not lines or lines[0].strip() != "---":
        return FrontmatterResult({}, "MISSING", required_fields, (), False)

    closing = next((index for index, line in enumerate(lines[1:], 1) if line.strip() == "---"), None)
    if closing is None:
        return FrontmatterResult(
            {},
            "INVALID",
            required_fields,
            ("Frontmatter is missing its closing '---' delimiter.",),
            False,
        )

    document = "\n".join(lines[1:closing])
    if not document.strip():
        return FrontmatterResult({}, "EMPTY", required_fields, (), False)
    document += "\n"
    if yaml is None:
        return FrontmatterResult(
            {},
            "INVALID",
            required_fields,
            ("PyYAML is required to parse SKILL.md frontmatter.",),
            False,
        )

    try:
        loaded = yaml.safe_load(document)
    except yaml.YAMLError as exc:
        problem = getattr(exc, "problem", None) or str(exc).splitlines()[0]
        return FrontmatterResult({}, "INVALID", required_fields, (f"Invalid YAML: {problem}",), False)

    if loaded is None:
        return FrontmatterResult({}, "EMPTY", required_fields, (), False)
    if not isinstance(loaded, dict):
        return FrontmatterResult(
            {},
            "INVALID",
            required_fields,
            ("Frontmatter must be a YAML mapping.",),
            False,
        )

    fields = {str(key): value for key, value in loaded.items()}
    missing = tuple(
        name
        for name in required_fields
        if not isinstance(fields.get(name), str) or not fields[name].strip()
    )
    errors = tuple(
        f"Required field '{name}' must be a non-empty string."
        for name in required_fields
        if name in fields and (not isinstance(fields[name], str) or not fields[name].strip())
    )
    return FrontmatterResult(fields, "VALID", missing, errors, not missing and not errors)


def parse_frontmatter_file(
    path: Path, required: Iterable[str] = ("name", "description")
) -> FrontmatterResult:
    required_fields = tuple(required)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return FrontmatterResult(
            {},
            "INVALID",
            required_fields,
            (f"Unable to read UTF-8 frontmatter: {exc}",),
            False,
        )
    return parse_frontmatter_text(text, required_fields)
