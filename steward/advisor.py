"""Turn inventory and usage into numbered, explained recommendations."""

from __future__ import annotations

import collections
import datetime as dt
import itertools
import re
import uuid
from typing import Any

from .sources import AGENTS, BUILTIN, PLUGIN, USER, Skill, fill_fingerprint
from .usage import AgentUsage, SkillUsage, usage_for

MIN_OBSERVED_DAYS = 30
MIN_USES_FOR_OPTIMIZE = 3
MIN_REWORK_FOR_OPTIMIZE = 2
REWORK_RATIO_FOR_OPTIMIZE = 0.25
COLLISION_THRESHOLD = 0.25
MAX_COLLISIONS_PER_AGENT = 6
FEW_CONVERSATIONS = 50

DELETE = "可以删除"
OPTIMIZE = "建议优化"
KEEP = "保持现状"

STOPWORDS = {
    "the", "and", "for", "use", "when", "with", "this", "that", "from", "into", "user", "users", "skill",
    "skills", "any", "are", "you", "your", "not", "can", "such", "also", "asks", "wants", "like", "via",
    "using", "used", "should", "must", "will", "its", "their", "them", "then", "than", "other", "only",
    "each", "more", "one", "all", "has", "have", "been", "who", "what", "which", "about", "over", "per",
}


def _days_between(start: str, end: str) -> int:
    try:
        return (dt.date.fromisoformat(end) - dt.date.fromisoformat(start)).days
    except ValueError:
        return 0


def _tokens(text: str) -> set[str]:
    lowered = text.lower()
    words = {word for word in re.findall(r"[a-z][a-z0-9-]{2,}", lowered) if word not in STOPWORDS}
    for run in re.findall(r"[㐀-鿿]{2,}", lowered):
        words.update(run[index : index + 2] for index in range(len(run) - 1))
    return words


def _similarity(left: str, right: str) -> float:
    a, b = _tokens(left), _tokens(right)
    if len(a) < 5 or len(b) < 5:
        return 0.0
    return len(a & b) / len(a | b)


def _label(skill: Skill) -> str:
    return f"{skill.name}（共享目录）" if skill.location.startswith("共享目录") else skill.name


def _same_family(left: str, right: str) -> bool:
    """Suite members such as baoyu-post-to-x / baoyu-post-to-weibo share a template."""
    a, b = left.lower().split("-", 1)[0], right.lower().split("-", 1)[0]
    return a == b and len(a) >= 4 and "-" in left and "-" in right


def _names_each_other(left: Skill, right: Skill) -> bool:
    """A description that names the other Skill has already drawn the boundary."""
    return right.name.lower() in left.description.lower() or left.name.lower() in right.description.lower()


def _other_agent_usage(skill: Skill, all_usage: dict[str, AgentUsage]) -> list[str]:
    notes = []
    for agent, agent_usage in all_usage.items():
        if agent == skill.agent or not agent_usage.available:
            continue
        count = usage_for(agent_usage, skill.usage_keys).count
        if count:
            notes.append(f"{agent} {count}{agent_usage.unit}")
    return notes


class Advisor:
    def __init__(self, skills: list[Skill], usage: dict[str, AgentUsage], today: str | None = None) -> None:
        self.skills = skills
        self.usage = usage
        self.today = today or dt.date.today().isoformat()
        self.items: list[dict[str, Any]] = []
        self.keep: dict[str, list[str]] = collections.defaultdict(list)
        self.skill_usage: dict[str, SkillUsage] = {}
        names = collections.Counter((skill.agent, skill.name.lower()) for skill in skills)
        for skill in skills:
            agent_usage = usage.get(skill.agent)
            keys = skill.usage_keys
            if names[(skill.agent, skill.name.lower())] > 1 and skill.scope_key:
                # Same-name copies in one Agent: count only reads of this folder.
                keys = {skill.scope_key}
            self.skill_usage[skill.key] = usage_for(agent_usage, keys) if agent_usage else SkillUsage()

    # -- helpers -----------------------------------------------------------------
    def _target(self, skill: Skill, *, fingerprint: bool) -> dict[str, Any]:
        if fingerprint:
            fill_fingerprint(skill)
        usage = self.skill_usage[skill.key]
        return {
            "agent": skill.agent,
            "name": skill.name,
            "path": skill.path,
            "source": skill.source,
            "location": skill.location,
            "tree_sha256": skill.tree_sha256,
            "modified_at": skill.modified_at,
            "uses": usage.count,
        }

    def _add(self, group: str, kind: str, title: str, reasons: list[str], targets: list[dict[str, Any]], **extra: Any) -> None:
        key = kind + "|" + "|".join(sorted(target["path"] for target in targets))
        self.items.append({"group": group, "kind": kind, "title": title, "reasons": reasons, "targets": targets, "key": key, **extra})

    def observed_days(self, skill: Skill) -> int:
        agent_usage = self.usage.get(skill.agent)
        if not agent_usage or not agent_usage.available or not agent_usage.since:
            return 0
        start = max(agent_usage.since, skill.installed_at or agent_usage.since)
        return _days_between(start, self.today)

    # -- rules -------------------------------------------------------------------
    def advise(self) -> list[dict[str, Any]]:
        handled: set[str] = set()
        self._mirrors(handled)
        self._collisions()
        self._plugins(handled)
        for skill in self.skills:
            if skill.key in handled:
                continue
            self._single(skill)
        kinds = ["delete", "uninstall_plugin", "optimize", "fix", "align", "collision"]
        agents = {agent: index for index, agent in enumerate(AGENTS)}
        self.items.sort(
            key=lambda item: (
                kinds.index(item["kind"]),
                agents.get(item["targets"][0]["agent"], 9) if item["kind"] == "delete" else 0,
                item["title"].lower(),
            )
        )
        for number, item in enumerate(self.items, 1):
            item["no"] = number
        return self.items

    def _single(self, skill: Skill) -> None:
        usage = self.skill_usage[skill.key]
        agent_usage = self.usage.get(skill.agent)
        label = _label(skill)
        if skill.source == BUILTIN:
            self.keep["系统自带，不建议改动"].append(label)
            return
        if skill.source == PLUGIN:
            self.keep["随插件安装，跟随插件整体管理"].append(label)
            return
        if skill.problems:
            self._add(
                OPTIMIZE,
                "fix",
                f"修复格式：{label}",
                [f"格式问题：{'；'.join(skill.problems)}", "格式不对时 Agent 可能识别不到或读错这个 Skill。"],
                [self._target(skill, fingerprint=True)],
            )
            return
        if not agent_usage or not agent_usage.available:
            self.keep[f"{skill.agent} 没有使用记录，无法判断"].append(label)
            return
        rework = len(usage.rework_sessions)
        if (
            usage.count >= MIN_USES_FOR_OPTIMIZE
            and rework >= MIN_REWORK_FOR_OPTIMIZE
            and rework / usage.count >= REWORK_RATIO_FOR_OPTIMIZE
        ):
            reasons = [
                f"用了 {usage.count}{agent_usage.unit}，其中 {rework} 次用完后你提出了修改意见（按关键词识别，疑似返工）。",
            ]
            reasons += [f"你当时说：“{example}”" for example in usage.rework_examples]
            self._add(OPTIMIZE, "optimize", f"根据使用记录优化：{label}", reasons, [self._target(skill, fingerprint=True)])
            return
        observed = self.observed_days(skill)
        if usage.count == 0:
            elsewhere = _other_agent_usage(skill, self.usage)
            if elsewhere and skill.location.startswith("共享目录"):
                # The shared .agents folder may also be read by other Agents.
                self.keep["共享目录里的 Skill，其他 Agent 在用"].append(f"{label}：{'、'.join(elsewhere)}")
                return
            if observed >= MIN_OBSERVED_DAYS:
                reasons = [f"在 {skill.agent} 里，安装以来有记录的 {observed} 天中一次都没用过。"]
                if agent_usage.unit == "次对话" and agent_usage.conversations < FEW_CONVERSATIONS:
                    reasons.append(f"{skill.agent} 本机只保留了 {agent_usage.conversations} 个对话记录，判断仅供参考。")
                reasons.append("删除会先放进 Darwin 回收站，随时可以恢复。")
                self._add(DELETE, "delete", f"删除：{label}", reasons, [self._target(skill, fingerprint=True)], observed_days=observed)
            else:
                self.keep[f"装了不到 {MIN_OBSERVED_DAYS} 天或记录太短，还看不出用不用"].append(label)
            return
        if usage.count >= MIN_USES_FOR_OPTIMIZE:
            self.keep["常用且没有明显返工"].append(f"{label} {usage.count}{agent_usage.unit}")
        else:
            self.keep["偶尔在用"].append(f"{label} {usage.count}{agent_usage.unit}")

    def _plugins(self, handled: set[str]) -> None:
        groups: dict[tuple[str, str], list[Skill]] = collections.defaultdict(list)
        for skill in self.skills:
            if skill.source == PLUGIN and skill.plugin:
                groups[(skill.agent, skill.plugin)].append(skill)
        for (agent, plugin), members in sorted(groups.items()):
            agent_usage = self.usage.get(agent)
            if not agent_usage or not agent_usage.available:
                continue
            total = sum(self.skill_usage[skill.key].count for skill in members)
            observed = min(self.observed_days(skill) for skill in members)
            if total == 0 and observed >= MIN_OBSERVED_DAYS:
                handled.update(skill.key for skill in members)
                self._add(
                    DELETE,
                    "uninstall_plugin",
                    f"卸载插件：{plugin}（含 {len(members)} 个 Skill）",
                    [
                        f"安装以来有记录的 {observed} 天里，插件内的 {len(members)} 个 Skill 一次都没用过。",
                        "插件需要在 Agent 自己的插件管理里卸载，Darwin 会告诉你具体怎么操作，不会自动卸载。",
                    ],
                    [self._target(skill, fingerprint=False) for skill in members],
                    plugin=plugin,
                    agent=agent,
                    observed_days=observed,
                )

    def _mirrors(self, handled: set[str]) -> None:
        by_name: dict[str, list[Skill]] = collections.defaultdict(list)
        for skill in self.skills:
            if skill.source == USER and skill.on_disk:
                by_name[skill.name.lower()].append(skill)
        for name, copies in sorted(by_name.items()):
            if len(copies) < 2:
                continue
            for copy in copies:
                fill_fingerprint(copy)
            if len({copy.tree_sha256 for copy in copies}) == 1:
                continue
            targets = [self._target(copy, fingerprint=True) for copy in copies]
            best = max(range(len(copies)), key=lambda i: (copies[i].modified_at, targets[i]["uses"]))
            lines = [
                f"{index + 1}) {copy.location}：最后修改 {copy.modified_at or '未知'}，用过 {targets[index]['uses']} 次"
                for index, copy in enumerate(copies)
            ]
            self._add(
                OPTIMIZE,
                "align",
                f"对齐副本：{copies[0].name}（{len(copies)} 份内容不一致）",
                [
                    f"{copies[0].agent} 同时能看到这几份，内容却不一样，可能用到旧版本。",
                    *lines,
                    f"建议统一成第 {best + 1} 份（最近修改）。其他副本会先放进回收站再替换，可恢复。",
                ],
                targets,
                recommended=best + 1,
            )

    def _collisions(self) -> None:
        by_agent: dict[str, list[Skill]] = collections.defaultdict(list)
        for skill in self.skills:
            if skill.description and skill.on_disk:
                by_agent[skill.agent].append(skill)
        for agent, members in sorted(by_agent.items()):
            pairs = []
            for left, right in itertools.combinations(members, 2):
                if left.name.lower() == right.name.lower():
                    continue
                if USER not in {left.source, right.source}:
                    continue
                if left.plugin and left.plugin == right.plugin:
                    continue
                if _same_family(left.name, right.name) or _names_each_other(left, right):
                    continue
                score = _similarity(left.description, right.description)
                if score >= COLLISION_THRESHOLD:
                    pairs.append((score, left, right))
            pairs.sort(key=lambda value: -value[0])
            seen: set[frozenset[str]] = set()
            for score, left, right in pairs[:MAX_COLLISIONS_PER_AGENT]:
                pair = frozenset({left.name.lower(), right.name.lower()})
                if pair in seen:
                    continue
                seen.add(pair)
                self._add(
                    OPTIMIZE,
                    "collision",
                    f"触发撞车：{left.name} ↔ {right.name}",
                    [
                        f"两个 Skill 的说明有 {score:.0%} 相似，Agent 可能在该用 A 时选了 B。",
                        f"{left.name}：{left.description[:60]}…",
                        f"{right.name}：{right.description[:60]}…",
                        "建议：改写说明，写清各自适用和不适用的场景；如果其实重复，也可以只留一个。",
                    ],
                    [self._target(left, fingerprint=left.source == USER), self._target(right, fingerprint=right.source == USER)],
                )


def build_report(
    skills: list[Skill], usage: dict[str, AgentUsage], today: str | None = None, agent: str | None = None
) -> dict[str, Any]:
    """Build one report. With ``agent``, only that Agent's Skills are covered;
    other Agents' usage is consulted solely to protect the shared .agents folder."""
    if agent:
        skills = [skill for skill in skills if skill.agent == agent]
    advisor = Advisor(skills, usage, today)
    items = advisor.advise()
    inventory = []
    for skill in skills:
        skill_usage = advisor.skill_usage[skill.key]
        agent_usage = usage.get(skill.agent)
        inventory.append(
            {
                **skill.as_dict(),
                "uses": skill_usage.count if agent_usage and agent_usage.available else None,
                "unit": agent_usage.unit if agent_usage else "",
                "last_used": skill_usage.last_used,
                "rework": len(skill_usage.rework_sessions),
            }
        )
    known = {key for skill in skills for key in skill.usage_keys}
    cloud = []
    for usage_agent, agent_usage in usage.items():
        if agent and usage_agent != agent:
            continue
        for name, skill_usage in agent_usage.skills.items():
            # Plugin-qualified names seen only in history are cloud or account Skills.
            if ":" in name and name not in known:
                cloud.append({"agent": usage_agent, "name": name, "uses": skill_usage.count, "last_used": skill_usage.last_used})
    return {
        "schema_version": 1,
        "report_id": uuid.uuid4().hex[:8],
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "agent": agent,
        "coverage": {
            name: {
                "available": value.available,
                "since": value.since,
                "until": value.until,
                "conversations": value.conversations,
                "unit": value.unit,
                "note": value.note,
            }
            for name, value in usage.items()
            if not agent or name == agent
        },
        "inventory": inventory,
        "cloud_used": sorted(cloud, key=lambda item: -item["uses"]),
        "items": items,
        "keep": {reason: names for reason, names in advisor.keep.items()},
    }
