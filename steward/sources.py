"""Find every installed Skill for Codex, Claude Code, WorkBuddy, and Doubao."""

from __future__ import annotations

from dataclasses import dataclass, field
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Iterable, Mapping

from darwin_core.frontmatter import parse_frontmatter_file

CODEX = "Codex"
CLAUDE = "Claude Code"
WORKBUDDY = "WorkBuddy"
DOUBAO = "豆包"
AGENTS = (CODEX, CLAUDE, WORKBUDDY, DOUBAO)

BUILTIN = "系统自带"
PLUGIN = "插件"
USER = "自己安装"

OFFICIAL_CODEX_PUBLISHERS = {"openai-bundled", "openai-curated", "openai-curated-remote", "openai-primary-runtime"}
BUILTIN_MARKETPLACES = {"workbuddy-builtin"}


@dataclass
class Skill:
    agent: str
    name: str
    path: str
    source: str
    location: str
    description: str = ""
    plugin: str | None = None
    problems: list[str] = field(default_factory=list)
    tree_sha256: str = ""
    modified_at: str = ""
    installed_at: str = ""
    usage_keys: set[str] = field(default_factory=set)
    scope_key: str = ""
    on_disk: bool = True

    @property
    def key(self) -> str:
        return f"{self.agent}|{self.path}"

    def as_dict(self) -> dict[str, object]:
        return {
            "agent": self.agent,
            "name": self.name,
            "path": self.path,
            "source": self.source,
            "location": self.location,
            "description": self.description,
            "plugin": self.plugin,
            "problems": list(self.problems),
            "tree_sha256": self.tree_sha256,
            "modified_at": self.modified_at,
            "installed_at": self.installed_at,
            "on_disk": self.on_disk,
        }


def tree_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(path.rglob("*"), key=lambda value: value.as_posix().lower()):
        relative = item.relative_to(path).as_posix()
        if any(part in {"__pycache__", ".git"} for part in Path(relative).parts) or item.is_dir():
            continue
        digest.update(relative.encode("utf-8") + b"\0")
        try:
            digest.update(item.read_bytes() if not item.is_symlink() else os.readlink(item).encode("utf-8"))
        except OSError:
            digest.update(b"<unreadable>")
        digest.update(b"\0")
    return digest.hexdigest()


def latest_mtime(path: Path) -> str:
    newest = 0.0
    for item in [path, *path.rglob("*")]:
        try:
            newest = max(newest, item.stat().st_mtime)
        except OSError:
            continue
    return dt.datetime.fromtimestamp(newest).strftime("%Y-%m-%d") if newest else ""


def skill_folders(root: Path) -> Iterable[Path]:
    """Yield Skill folders under root, without descending into a found Skill."""
    if not root.is_dir():
        return
    stack = [root]
    while stack:
        current = stack.pop()
        if (current / "SKILL.md").is_file():
            yield current
            continue
        try:
            children = sorted(child for child in current.iterdir() if child.is_dir())
        except OSError:
            continue
        stack.extend(reversed([child for child in children if child.name not in {".git", "__pycache__", "node_modules"}]))


def build_skill(
    agent: str, folder: Path, source: str, location: str, plugin: str | None = None, scope: str = ""
) -> Skill:
    result = parse_frontmatter_file(folder / "SKILL.md")
    declared = result.fields.get("name")
    name = declared.strip() if isinstance(declared, str) and declared.strip() else folder.name
    description = result.fields.get("description")
    problems = list(result.parse_errors)
    if result.status == "MISSING":
        problems.append("SKILL.md 缺少开头的 --- 元信息块")
    elif result.status == "EMPTY":
        problems.append("SKILL.md 元信息块是空的")
    for missing in result.missing_required_fields:
        if result.status == "VALID":
            problems.append(f"缺少必填字段 {missing}")
    problems.extend(_comment_truncation(folder / "SKILL.md"))
    keys = {name, folder.name}
    if plugin:
        keys |= {f"{plugin}:{name}", f"{plugin}:{folder.name}"}
    return Skill(
        agent=agent,
        name=name,
        path=str(folder.resolve()),
        source=source,
        location=location,
        description=" ".join(description.split()) if isinstance(description, str) else _body_hint(folder),
        plugin=plugin,
        problems=problems,
        installed_at=_installed_at(folder),
        usage_keys=keys,
        scope_key=f"@{scope}/{folder.name}" if scope else "",
    )


def _comment_truncation(skill_md: Path) -> list[str]:
    """An unquoted ' #' starts a YAML comment, silently cutting the value short."""
    try:
        lines = skill_md.read_text(encoding="utf-8", errors="replace").lstrip("﻿").splitlines()
    except OSError:
        return []
    if not lines or lines[0].strip() != "---":
        return []
    problems = []
    for line in lines[1:]:
        if line.strip() == "---":
            break
        match = re.match(r"(name|description):\s*([^|>'\"\s].*?)\s#", line)
        if match:
            problems.append(f"{match.group(1)} 被 # 截断")
    return problems


def _body_hint(folder: Path) -> str:
    """First meaningful line of a SKILL.md that has no description, for display."""
    try:
        lines = (folder / "SKILL.md").read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    for line in lines:
        text = line.strip().lstrip("#").strip()
        if text and text != "---" and ":" not in text[:20]:
            return text[:200]
    return ""


def _installed_at(folder: Path) -> str:
    """Install date = when the Skill folder was created on this machine.

    File modification times are not used: copying or unzipping a Skill keeps
    the author's old mtimes, which made fresh installs look months old.
    """
    try:
        stat = folder.stat()
    except OSError:
        return ""
    # st_birthtime on macOS/BSD; on Windows st_ctime is the creation time.
    created = getattr(stat, "st_birthtime", None) or stat.st_ctime
    return dt.datetime.fromtimestamp(created).strftime("%Y-%m-%d")


def fill_fingerprint(skill: Skill) -> Skill:
    """Hash a Skill tree on demand; some Skills hold thousands of files."""
    if skill.on_disk and not skill.tree_sha256:
        folder = Path(skill.path)
        skill.tree_sha256 = tree_sha256(folder)
        skill.modified_at = latest_mtime(folder)
    return skill


def _installed_plugins(manifest: Path) -> list[tuple[str, str, Path]]:
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    result = []
    for key, installs in (data.get("plugins") or {}).items():
        plugin, _, marketplace = key.partition("@")
        for install in installs if isinstance(installs, list) else []:
            path = install.get("installPath") if isinstance(install, dict) else None
            if path:
                result.append((plugin, marketplace, Path(path)))
    return result


def _codex_plugin_versions(cache: Path) -> Iterable[tuple[str, str, Path]]:
    """Yield the active (or most recent) version folder of each Codex plugin."""
    from adapters.codex import _active_plugin_version

    if not cache.is_dir():
        return
    for publisher in sorted(p for p in cache.iterdir() if p.is_dir()):
        for plugin_root in sorted(p for p in publisher.iterdir() if p.is_dir()):
            active, _ = _active_plugin_version(plugin_root)
            if active:
                version = plugin_root / active
            else:
                versions = [p for p in plugin_root.iterdir() if p.is_dir() and p.name != "latest"]
                if not versions:
                    continue
                version = max(versions, key=lambda p: p.stat().st_mtime)
            yield publisher.name, plugin_root.name, version


def discover_codex(home: Path) -> list[Skill]:
    skills: list[Skill] = []
    user_root = home / ".codex" / "skills"
    for folder in skill_folders(user_root):
        if ".system" in folder.relative_to(user_root).parts:
            skills.append(build_skill(CODEX, folder, BUILTIN, "Codex 系统目录", scope=".codex"))
        else:
            skills.append(build_skill(CODEX, folder, USER, "Codex 用户目录", scope=".codex"))
    for folder in skill_folders(home / ".agents" / "skills"):
        skills.append(build_skill(CODEX, folder, USER, "共享目录 .agents", scope=".agents"))
    for publisher, plugin, version in _codex_plugin_versions(home / ".codex" / "plugins" / "cache"):
        source = BUILTIN if publisher in OFFICIAL_CODEX_PUBLISHERS else PLUGIN
        for folder in skill_folders(version):
            skills.append(build_skill(CODEX, folder, source, f"插件 {plugin}", plugin=plugin, scope="plugin"))
    return skills


def discover_claude(home: Path) -> list[Skill]:
    skills = [build_skill(CLAUDE, folder, USER, "Claude 用户目录") for folder in skill_folders(home / ".claude" / "skills")]
    for plugin, _marketplace, path in _installed_plugins(home / ".claude" / "plugins" / "installed_plugins.json"):
        for folder in skill_folders(path):
            skills.append(build_skill(CLAUDE, folder, PLUGIN, f"插件 {plugin}", plugin=plugin))
    return skills


def discover_workbuddy(home: Path) -> list[Skill]:
    skills = [build_skill(WORKBUDDY, folder, USER, "WorkBuddy 用户目录") for folder in skill_folders(home / ".workbuddy" / "skills")]
    for plugin, marketplace, path in _installed_plugins(home / ".workbuddy" / "plugins" / "installed_plugins.json"):
        source = BUILTIN if marketplace in BUILTIN_MARKETPLACES else PLUGIN
        for folder in skill_folders(path):
            skills.append(build_skill(WORKBUDDY, folder, source, f"插件 {plugin}", plugin=plugin))
    return skills


def discover_doubao(home: Path, extra_roots: Iterable[Path] = ()) -> list[Skill]:
    skills = []
    for root in [home / "Doubao" / "skills", *extra_roots]:
        for folder in skill_folders(root):
            skills.append(build_skill(DOUBAO, folder, USER, "豆包 Skill 目录"))
    return skills


AGENT_ALIASES = {
    "codex": CODEX,
    "claude": CLAUDE,
    "claude-code": CLAUDE,
    "claude_code": CLAUDE,
    "workbuddy": WORKBUDDY,
    "codebuddy": WORKBUDDY,
    "doubao": DOUBAO,
    "豆包": DOUBAO,
}


def resolve_agent(value: str | None, environ: Mapping[str, str] | None = None) -> str | None:
    """Return the Agent to inventory: explicit value first, then the running Agent."""
    if value:
        agent = AGENT_ALIASES.get(value.strip().lower())
        if not agent:
            raise ValueError(f"不认识的 Agent：{value}（可选 codex / claude / workbuddy / doubao）")
        return agent
    env = os.environ if environ is None else environ
    if env.get("CLAUDECODE"):
        return CLAUDE
    if any(key.startswith(("CODEBUDDY_", "WORKBUDDY_")) for key in env):
        return WORKBUDDY
    if any(key.startswith("CODEX_") and key != "CODEX_HOME" for key in env):
        return CODEX
    return None


def discover_all(
    home: Path | None = None, doubao_roots: Iterable[Path] = (), agents: Iterable[str] | None = None
) -> list[Skill]:
    home = (home or Path.home()).expanduser()
    wanted = set(agents or AGENTS)
    finders = {
        CODEX: lambda: discover_codex(home),
        CLAUDE: lambda: discover_claude(home),
        WORKBUDDY: lambda: discover_workbuddy(home),
        DOUBAO: lambda: discover_doubao(home, doubao_roots),
    }
    skills = [skill for agent in AGENTS if agent in wanted for skill in finders[agent]()]
    seen: set[str] = set()
    unique = []
    for skill in skills:
        if skill.key not in seen:
            seen.add(skill.key)
            unique.append(skill)
    return unique


def user_skill_roots(home: Path | None = None) -> list[Path]:
    """Folders where Darwin may move or replace a user-installed Skill."""
    home = (home or Path.home()).expanduser()
    return [
        (home / ".codex" / "skills").resolve(),
        (home / ".agents" / "skills").resolve(),
        (home / ".claude" / "skills").resolve(),
        (home / ".workbuddy" / "skills").resolve(),
        (home / "Doubao" / "skills").resolve(),
    ]
