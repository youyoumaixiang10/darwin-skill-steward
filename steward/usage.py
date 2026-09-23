"""Read real Skill usage from each Agent's local history.

Counts are the number of distinct conversations that used a Skill. A
conversation also counts as "rework" when the user asked for corrections
after the Skill was used; this is a keyword heuristic, labelled as such.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from typing import Any, Iterable, Iterator

from .sources import CLAUDE, CODEX, DOUBAO, WORKBUDDY

REWORK_PATTERN = re.compile(
    r"不对|不行|错了|有误|重做|返工|不是这样|不是我要|不满意|没按|不符合|还是不|太啰嗦|跑偏|理解错|"
    r"\bwrong\b|\bredo\b|not what i",
    re.IGNORECASE,
)
# Only the user's next few messages after a Skill ran are attributed to it.
REWORK_WINDOW = 3
MAX_FEEDBACK_CHARS = 400
SKILL_PATH = re.compile(r"skills[\\/]+(?:\.system[\\/]+)?([^\\/\"'\s`<>|]+)[\\/]+SKILL\.md", re.IGNORECASE)
INSTALLED_MARKERS = (".codex", ".agents", "plugins")
CODEX_SKILL_BLOCK = re.compile(r"<skill>\s*<name>([^<]+)</name>")
# Cheap pre-filter: only these Codex lines can carry usage, feedback, or dates.
CODEX_NEEDLES = ("SKILL.md", '"role":"user"', '"role": "user"', '"session_meta"')
CLAUDE_COMMAND = re.compile(r"<command-name>/?([^<\s]+)</command-name>")


@dataclass
class SkillUsage:
    sessions: set[str] = field(default_factory=set)
    rework_sessions: set[str] = field(default_factory=set)
    rework_examples: list[str] = field(default_factory=list)
    last_used: str = ""
    count_override: int | None = None

    @property
    def count(self) -> int:
        return self.count_override if self.count_override is not None else len(self.sessions)

    def mark(self, session: str, timestamp: str) -> None:
        self.sessions.add(session)
        day = (timestamp or "")[:10]
        if day > self.last_used:
            self.last_used = day


@dataclass
class AgentUsage:
    agent: str
    available: bool
    since: str = ""
    until: str = ""
    conversations: int = 0
    unit: str = "次对话"
    note: str = ""
    skills: dict[str, SkillUsage] = field(default_factory=dict)

    def usage(self, name: str) -> SkillUsage:
        return self.skills.setdefault(name, SkillUsage())

    def observe_time(self, timestamp: str) -> None:
        day = (timestamp or "")[:10]
        if not re.match(r"\d{4}-\d{2}-\d{2}", day):
            return
        if not self.since or day < self.since:
            self.since = day
        if day > self.until:
            self.until = day


def _json_lines(path: Path, needles: tuple[str, ...]) -> Iterator[dict[str, Any]]:
    try:
        handle = path.open(encoding="utf-8", errors="replace")
    except OSError:
        return
    with handle:
        for line in handle:
            if needles and not any(needle in line for needle in needles):
                continue
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict):
                yield value


def _is_typed_text(text: str) -> bool:
    stripped = text.strip()
    return (
        bool(stripped)
        and len(stripped) <= MAX_FEEDBACK_CHARS
        and not stripped.startswith(("<", "# AGENTS.md", "Caveat:", "[Request interrupted"))
    )


def _snippet(text: str) -> str:
    compact = " ".join(text.split())
    return compact[:80] + ("…" if len(compact) > 80 else "")


def _record_rework(agent: AgentUsage, active: dict[str, int], session: str, text: str) -> None:
    """Attribute a correction to Skills used within the last few user messages."""
    if REWORK_PATTERN.search(text):
        for name in active:
            usage = agent.usage(name)
            if session not in usage.rework_sessions:
                usage.rework_sessions.add(session)
                if len(usage.rework_examples) < 3:
                    usage.rework_examples.append(_snippet(text))
    for name in list(active):
        active[name] -= 1
        if active[name] <= 0:
            del active[name]


def read_claude(home: Path) -> AgentUsage:
    root = home / ".claude" / "projects"
    agent = AgentUsage(CLAUDE, available=root.is_dir())
    for path in sorted(root.rglob("*.jsonl")) if root.is_dir() else []:
        session = str(path)
        active: dict[str, int] = {}
        seen_any = False
        for entry in _json_lines(path, ()):
            timestamp = str(entry.get("timestamp") or "")
            agent.observe_time(timestamp)
            seen_any = seen_any or bool(timestamp)
            message = entry.get("message") if isinstance(entry.get("message"), dict) else {}
            content = message.get("content")
            items = content if isinstance(content, list) else [{"type": "text", "text": content}] if isinstance(content, str) else []
            if entry.get("type") == "assistant":
                for item in items:
                    if isinstance(item, dict) and item.get("type") == "tool_use" and item.get("name") == "Skill":
                        name = str((item.get("input") or {}).get("skill") or "").strip()
                        if name:
                            agent.usage(name).mark(session, timestamp)
                            active[name] = REWORK_WINDOW
            elif entry.get("type") == "user":
                for item in items:
                    if not isinstance(item, dict) or item.get("type") != "text":
                        continue
                    text = str(item.get("text") or "")
                    for name in CLAUDE_COMMAND.findall(text):
                        agent.usage(name).mark(session, timestamp)
                        active[name] = REWORK_WINDOW
                    if _is_typed_text(text):
                        _record_rework(agent, active, session, text)
        agent.conversations += int(seen_any)
    agent.note = "Claude Code 默认会自动清理较早的对话记录，统计只覆盖本机还保留的对话。"
    return agent


def scoped_key(path_text: str, name: str) -> str:
    """Name a Codex Skill by the folder it was read from, e.g. '@.agents/web-access'.

    Codex sees both ~/.codex/skills and ~/.agents/skills, so two same-name
    copies can only be told apart by the path that was actually read.
    """
    lowered = path_text.replace("\\\\", "\\").lower()
    candidates = {
        ".codex": max(lowered.rfind(".codex\\skills"), lowered.rfind(".codex/skills")),
        ".agents": max(lowered.rfind(".agents\\skills"), lowered.rfind(".agents/skills")),
        "plugin": max(lowered.rfind("plugins\\cache"), lowered.rfind("plugins/cache")),
    }
    root = max(candidates, key=lambda key: candidates[key])
    return f"@{root}/{name}" if candidates[root] >= 0 else f"@unknown/{name}"


def _codex_call_text(payload: dict[str, Any]) -> str:
    text = str(payload.get("arguments") or payload.get("input") or "")
    if "*** Begin Patch" in text:
        return ""
    return text


def read_codex(home: Path) -> AgentUsage:
    root = home / ".codex" / "sessions"
    agent = AgentUsage(CODEX, available=root.is_dir())
    for path in sorted(root.rglob("*.jsonl")) if root.is_dir() else []:
        session = str(path)
        active: dict[str, int] = {}
        agent.conversations += 1
        for entry in _json_lines(path, CODEX_NEEDLES):
            timestamp = str(entry.get("timestamp") or "")
            agent.observe_time(timestamp)
            if entry.get("type") != "response_item":
                continue
            payload = entry.get("payload") if isinstance(entry.get("payload"), dict) else {}
            kind = payload.get("type")
            if kind in {"function_call", "custom_tool_call"}:
                text = _codex_call_text(payload)
                if "SKILL.md" not in text:
                    continue
                for match in SKILL_PATH.finditer(text):
                    window = text[max(0, match.start() - 200) : match.end()]
                    if "http" in window.lower() or not any(marker in window for marker in INSTALLED_MARKERS):
                        continue
                    for name in (match.group(1), scoped_key(window, match.group(1))):
                        agent.usage(name).mark(session, timestamp)
                        active[name] = REWORK_WINDOW
            elif kind == "message" and payload.get("role") == "user":
                for item in payload.get("content") or []:
                    text = str(item.get("text") or "") if isinstance(item, dict) else ""
                    for block in CODEX_SKILL_BLOCK.finditer(text):
                        name = block.group(1).strip()
                        path = text[block.end() : block.end() + 300]
                        for key in (name, scoped_key(path, name)):
                            agent.usage(key).mark(session, timestamp)
                            active[key] = REWORK_WINDOW
                    if _is_typed_text(text):
                        _record_rework(agent, active, session, text)
    return agent


def read_workbuddy(home: Path) -> AgentUsage:
    path = home / ".workbuddy" / "usage-log.json"
    agent = AgentUsage(WORKBUDDY, available=path.is_file(), unit="天")
    agent.note = "WorkBuddy 只记录每个 Skill 最近用过的日期，次数按“用过的天数”计。"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        agent.available = False
        return agent
    for day in data.get("activeDays") or []:
        agent.observe_time(str(day))
    for name, item in (data.get("skills") or {}).items():
        if not isinstance(item, dict):
            continue
        dates = sorted({str(day) for day in item.get("recentDates") or []})
        usage = agent.usage(str(item.get("id") or name))
        usage.sessions = set(dates)
        usage.last_used = str(item.get("lastUsedDate") or (dates[-1] if dates else ""))
        agent.observe_time(str(item.get("firstSeenDate") or ""))
        for day in dates:
            agent.observe_time(day)
    agent.conversations = len(data.get("activeDays") or [])
    return agent


def read_doubao(home: Path) -> AgentUsage:
    return AgentUsage(DOUBAO, available=False, note="豆包客户端没有可读取的 Skill 使用记录，无法统计次数。")


def read_all(home: Path | None = None, agents: Iterable[str] | None = None) -> dict[str, AgentUsage]:
    home = (home or Path.home()).expanduser()
    readers = {CODEX: read_codex, CLAUDE: read_claude, WORKBUDDY: read_workbuddy, DOUBAO: read_doubao}
    wanted = set(agents or readers)
    return {agent: reader(home) for agent, reader in readers.items() if agent in wanted}


def usage_for(agent_usage: AgentUsage, keys: Iterable[str]) -> SkillUsage:
    """Merge the usage recorded under any of a Skill's names."""
    merged = SkillUsage()
    for key in keys:
        usage = agent_usage.skills.get(key)
        if not usage:
            continue
        merged.sessions |= usage.sessions
        merged.rework_sessions |= usage.rework_sessions
        for example in usage.rework_examples:
            if example not in merged.rework_examples and len(merged.rework_examples) < 3:
                merged.rework_examples.append(example)
        merged.last_used = max(merged.last_used, usage.last_used)
    return merged
