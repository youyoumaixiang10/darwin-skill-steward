"""Numbered, layered rows: the one table the user reads and replies to.

Every user-installed Skill and every plugin gets a row number. Replies such as
"删 5" or "优化 12" refer to these numbers, always within one report.
Built-in Skills are listed but not numbered because Darwin never changes them.
"""

from __future__ import annotations

import collections
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from . import summaries
from .sources import BUILTIN, PLUGIN, USER

RESIDENT = "常驻"
WORKFLOW = "工作流"
TRIAL = "实验区"
LAYERS = (RESIDENT, WORKFLOW, TRIAL)
LAYER_MEANING = {
    RESIDENT: "高频、通用的基础能力",
    WORKFLOW: "你反复做的具体任务",
    TRIAL: "新装的、没用起来的，先观察再决定去留",
}

PROBLEM_TEXT = [
    ("缺少开头", "说明文件（SKILL.md）开头缺少名称和简介，{agent} 可能认不出这个 Skill，或者不知道什么时候该用它"),
    ("元信息块是空的", "说明文件开头的名称和简介是空的，{agent} 不知道这个 Skill 是干什么的"),
    ("Invalid YAML", "说明文件开头的名称/简介有格式错误，{agent} 可能读不到简介，该用时想不起来用它"),
    ("缺少必填字段 name", "说明文件开头缺少名称"),
    ("缺少必填字段 description", "说明文件开头缺少简介，{agent} 不知道什么时候该用它"),
    ("Required field", "说明文件开头的名称或简介不是有效文字"),
    ("description 被 # 截断", "简介里有个 # 号（如颜色值 #ff5722），# 后面的内容被当成注释丢掉了，{agent} 只读到半句简介，可能该用时想不起来用它"),
    ("name 被 # 截断", "名称里有个 # 号，# 后面的内容被当成注释丢掉了，名称不完整"),
]


def explain_problem(problem: str, agent: str) -> str:
    for marker, text in PROBLEM_TEXT:
        if marker in problem:
            return text.format(agent=agent)
    return problem


def stat_signature(path: Path) -> str:
    """Cheap change detector: file names, sizes, and modification times."""
    digest = hashlib.sha256()
    for item in sorted(path.rglob("*"), key=lambda value: value.as_posix().lower()):
        relative = item.relative_to(path).as_posix()
        if any(part in {"__pycache__", ".git"} for part in Path(relative).parts) or item.is_dir():
            continue
        try:
            stat = item.lstat()
        except OSError:
            continue
        digest.update(f"{relative}\0{stat.st_size}\0{stat.st_mtime_ns}\0".encode("utf-8"))
    return digest.hexdigest()


def plugin_summary_key(name: str, members: list[str]) -> str:
    return summaries.summary_key(f"plugin:{name}", "、".join(sorted(members)))


def _override_key(agent: str, row: dict[str, Any]) -> str:
    return f"{agent}|plugin:{row['plugin']}" if row["kind"] == "plugin" else f"{agent}|{row['name']}"


def load_overrides(home: Path) -> dict[str, str]:
    try:
        value = json.loads((home / "layers.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): str(v) for k, v in value.items() if v in LAYERS} if isinstance(value, dict) else {}


def save_override(home: Path, agent: str, row: dict[str, Any], layer: str) -> None:
    if layer not in LAYERS:
        raise ValueError(f"分层只能是：{'、'.join(LAYERS)}")
    overrides = load_overrides(home)
    overrides[_override_key(agent, row)] = layer
    home.mkdir(parents=True, exist_ok=True)
    temp = home / "layers.json.tmp"
    temp.write_text(json.dumps(overrides, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, home / "layers.json")


def _layer(row: dict[str, Any], kind_hint: str | None, override: str | None) -> tuple[str, str]:
    if override:
        return override, "你指定的"
    if row["uses"] == 0:
        return TRIAL, "没用过"
    hint = kind_hint if kind_hint in (RESIDENT, WORKFLOW) else WORKFLOW
    return hint, ("无法统计使用，按用途分" if row["uses"] is None else "按用途分")


def build_rows(report: dict[str, Any], cache: dict[str, Any], overrides: dict[str, str]) -> list[dict[str, Any]]:
    agent = report.get("agent") or ""
    inventory = report["inventory"]
    rows: list[dict[str, Any]] = []
    for skill in inventory:
        if skill["source"] != USER:
            continue
        summary, hint = summaries.lookup(cache, summaries.summary_key(skill["name"], skill.get("description", "")))
        row = {
            "kind": "skill",
            "name": skill["name"],
            "agent": skill["agent"],
            "source": USER,
            "location": skill["location"],
            "path": skill["path"],
            "paths": [skill["path"]],
            "summary": summary or summaries.fallback(skill.get("description", "")),
            "uses": skill["uses"],
            "last_used": skill["last_used"],
            "rework": skill.get("rework", 0),
            "problems": skill["problems"],
            "tree_sha256": skill.get("tree_sha256", ""),
            "stat_sig": stat_signature(Path(skill["path"])) if Path(skill["path"]).is_dir() else "",
        }
        row["layer"], row["layer_reason"] = _layer(row, hint, overrides.get(_override_key(skill["agent"], row)))
        rows.append(row)

    plugins: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for skill in inventory:
        if skill["source"] == PLUGIN and skill.get("plugin"):
            plugins[skill["plugin"]].append(skill)
    for name, members in sorted(plugins.items()):
        member_names = [m["name"] for m in members]
        summary, hint = summaries.lookup(cache, plugin_summary_key(name, member_names))
        uses = None if any(m["uses"] is None for m in members) else sum(m["uses"] for m in members)
        row = {
            "kind": "plugin",
            "name": f"📦 插件 {name}（{len(members)} 个 Skill）",
            "plugin": name,
            "agent": members[0]["agent"],
            "source": PLUGIN,
            "location": f"插件 {name}",
            "path": "",
            "paths": [m["path"] for m in members],
            "members": sorted(member_names),
            "summary": summary or "、".join(sorted(member_names)[:4]) + ("等" if len(members) > 4 else ""),
            "uses": uses,
            "last_used": max((m["last_used"] for m in members), default=""),
            "rework": 0,
            "problems": [],
        }
        row["layer"], row["layer_reason"] = _layer(row, hint, overrides.get(_override_key(row["agent"], row)))
        rows.append(row)

    rows.sort(key=lambda r: (LAYERS.index(r["layer"]), -(r["uses"] or 0), r["kind"] == "plugin", r["name"].lower()))
    for number, row in enumerate(rows, 1):
        row["no"] = number
    _attach_notes(rows, report)
    return rows


def finalize(report: dict[str, Any], store: Path) -> dict[str, Any]:
    """Add cached summaries and the numbered, layered rows to a report."""
    cache = summaries.load(store)
    for item in report["inventory"]:
        summary, _ = summaries.lookup(cache, summaries.summary_key(item["name"], item.get("description", "")))
        item["summary"] = summary or summaries.fallback(item.get("description", ""))
    report["rows"] = build_rows(report, cache, load_overrides(store))
    return report


def _attach_notes(rows: list[dict[str, Any]], report: dict[str, Any]) -> None:
    by_path = {path: row for row in rows for path in row["paths"]}
    items_by_path: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for item in report.get("items", []):
        for target in item["targets"]:
            items_by_path[target["path"]].append(item)
    plugin_rows = [row for row in rows if row["kind"] == "plugin"]

    for row in rows:
        notes: list[str] = []
        suggestions: list[str] = []
        related = [item for path in row["paths"] for item in items_by_path.get(path, [])]
        kinds = {item["kind"]: item for item in related}
        if row["problems"]:
            problem = "；".join(dict.fromkeys(explain_problem(p, row["agent"]) for p in row["problems"]))
            notes.append(f"⚠️ {problem}。建议：优化（我来补全修好）")
            suggestions.append("优化")
        if "optimize" in kinds:
            notes.append(f"🔧 用完后有 {row['rework']} 次你提了修改意见（疑似返工）。建议：优化（按你的反馈改进）")
            suggestions.append("优化")
        if "delete" in kinds:
            notes.append(f"💤 装了 {kinds['delete'].get('observed_days', '')} 天一次都没用过。建议：删除（进回收站，能恢复）")
            suggestions.append("删")
        if "uninstall_plugin" in kinds:
            days = kinds["uninstall_plugin"].get("observed_days", "")
            notes.append(f"💤 装了 {days} 天，里面的 Skill 一次都没用过。建议：卸载（需要在 Agent 里手动操作，我给步骤）")
            suggestions.append("删")
        if "align" in kinds and row["kind"] == "skill":
            item = kinds["align"]
            copies = [by_path[t["path"]] for t in item["targets"] if t["path"] in by_path]
            best = item["targets"][item["recommended"] - 1]["path"]
            others = "、".join(f"第 {c['no']} 行" for c in copies if c is not row)
            if best == row["path"]:
                advice = "建议：对齐（把其他几份统一成这份，这份最新）"
            else:
                advice = f"建议：对齐（统一成第 {by_path[best]['no']} 行那份，那份最新）"
            notes.append(f"📑 {row['agent']} 里还有同名副本（{others}），内容不一样，可能用到旧版。{advice}")
            suggestions.append("对齐")
        for item in related:
            if item["kind"] != "collision":
                continue
            other = next((t for t in item["targets"] if t["path"] not in row["paths"]), None)
            if other and other["path"] in by_path:
                notes.append(f"🔀 和第 {by_path[other['path']]['no']} 行 {other['name']} 的简介很像，{row['agent']} 可能选错。建议：优化（改写简介，分清用途）")
                suggestions.append("优化")
        if row["kind"] == "skill":
            for plugin in plugin_rows:
                if row["name"] in plugin["members"]:
                    notes.append(f"👯 和第 {plugin['no']} 行插件 {plugin['plugin']} 里的 {row['name']} 重名，{row['agent']} 里会出现两个。建议：只留一个")
        else:
            overlaps = [other for other in plugin_rows if other is not row and set(row["members"]) & set(other["members"])]
            if overlaps:
                shared = sorted({name for other in overlaps for name in set(row["members"]) & set(other["members"])})
                where = "、".join(str(other["no"]) for other in overlaps)
                notes.append(
                    f"👯 其中 {len(shared)} 个 Skill 和第 {where} 行插件重复（{'、'.join(shared[:3])}{'等' if len(shared) > 3 else ''}），同一件事 {row['agent']} 里有好几个同名 Skill 可选"
                )
            twins = [other for other in rows if other["kind"] == "skill" and other["name"] in row["members"]]
            for twin in twins:
                notes.append(f"👯 里面的 {twin['name']} 和第 {twin['no']} 行你自己装的重名，{row['agent']} 里会出现两个。建议：只留一个")
        if not notes and row["uses"] == 0:
            notes.append("还没用过，装的时间不长，先观察")
        row["notes"] = notes
        row["suggestions"] = list(dict.fromkeys(suggestions))
