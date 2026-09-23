"""Render steward reports as short Chinese Markdown for a chat reply.

Everything the user can act on is one numbered row; replies use those numbers.
"""

from __future__ import annotations

import collections
from typing import Any

from .rows import LAYER_MEANING, LAYERS, TRIAL
from .sources import AGENTS, BUILTIN, PLUGIN, USER


def _uses(row: dict[str, Any]) -> str:
    return "无法统计" if row.get("uses") is None else str(row["uses"])


def _agents(report: dict[str, Any]) -> list[str]:
    return [report["agent"]] if report.get("agent") else list(AGENTS)


def coverage_lines(report: dict[str, Any]) -> list[str]:
    lines = []
    for agent in _agents(report):
        value = report["coverage"].get(agent) or {}
        if not value.get("available"):
            lines.append(f"- **{agent}**：{value.get('note') or '没有找到使用记录'}")
            continue
        span = f"{value['since']} 至 {value['until']}" if value.get("since") else "时间未知"
        count = f"，共 {value['conversations']} 个对话" if value.get("unit") == "次对话" else ""
        note = f" {value['note']}" if value.get("note") else ""
        lines.append(f"- **{agent}**：记录覆盖 {span}{count}。{note}".rstrip())
    return lines


def _unit(report: dict[str, Any]) -> str:
    return "天" if report.get("agent") == "WorkBuddy" else "次"


def _table(rows: list[dict[str, Any]], unit: str) -> list[str]:
    out = [f"| 序号 | Skill | 功能 | 使用{unit}数 | 最近使用 | 备注（问题与建议） |", "|---|---|---|---|---|---|"]
    for row in rows:
        notes = "<br>".join(row["notes"]) or "正常"
        out.append(f"| {row['no']} | {row['name']} | {row['summary']} | {_uses(row)} | {row['last_used'] or '—'} | {notes} |")
    return out


def _header(report: dict[str, Any], title: str) -> list[str]:
    heading = f"# {report['agent']} 的 {title}" if report.get("agent") else f"# {title}"
    return [heading, "", f"报告编号 `{report['report_id']}`，生成于 {report['generated_at'][:16].replace('T', ' ')}", ""]


def inventory_markdown(report: dict[str, Any], full: bool = False) -> str:
    rows = report["rows"]
    inventory = report["inventory"]
    counts = collections.Counter(item["source"] for item in inventory)
    out = _header(report, "Skills 盘点")
    out.append(
        f"共 {len(inventory)} 个 Skill：自己安装 {counts[USER]} 个、插件带的 {counts[PLUGIN]} 个、系统自带 {counts[BUILTIN]} 个。"
    )
    out += ["", "**使用次数怎么来的**（只统计本机保存的记录）：", *coverage_lines(report), ""]
    unit = _unit(report)
    for layer in LAYERS:
        group = [row for row in rows if row["layer"] == layer]
        if not group:
            continue
        out += [f"## {layer}（{len(group)} 个）：{LAYER_MEANING[layer]}", "", *_table(group, unit), ""]
    plugin_rows = [row for row in rows if row["kind"] == "plugin"]
    if full and plugin_rows:
        out += ["**插件里包含的 Skill**", ""]
        member_summary = {item["name"]: item.get("summary", "") for item in inventory if item["source"] == PLUGIN}
        for row in plugin_rows:
            parts = [f"{name}（{member_summary.get(name)}）" if member_summary.get(name) else name for name in row["members"]]
            out.append(f"- 第 {row['no']} 行 {row['plugin']}：{'、'.join(parts)}")
        out.append("")
    builtin = [item for item in inventory if item["source"] == BUILTIN]
    if builtin:
        used = [f"{item['name']} {item['uses']}" for item in sorted(builtin, key=lambda r: -(r["uses"] or 0)) if item.get("uses")]
        line = f"**系统自带（{len(builtin)} 个，不编号，Darwin 不会动）**：" + (f"用过的有 {'、'.join(used)}" if used else "都没用过")
        out.append(line)
        if full:
            out.append("包含：" + "、".join(sorted(item["name"] for item in builtin)))
        out.append("")
    cloud = report.get("cloud_used", [])
    if cloud:
        out += ["**账号里的云端 Skill（本机没有文件，只能统计到用过的）**：" + "、".join(f"{c['name']} {c['uses']}次" for c in cloud), ""]
    out += ["---", *_how_to_choose(report)]
    return "\n".join(out)


def advice_markdown(report: dict[str, Any]) -> str:
    rows = report["rows"]
    out = _header(report, "Skills 优化建议")
    out += ["依据：", *coverage_lines(report), "", "序号和盘点表一致。", ""]
    deletes = [row for row in rows if "删" in row["suggestions"]]
    fixes = [row for row in rows if {"优化", "对齐"} & set(row["suggestions"])]
    keep = [row for row in rows if not row["suggestions"]]
    for title, group in (("🗑 建议删除 / 卸载", deletes), ("🔧 建议优化", fixes)):
        out += [f"## {title}（{len(group)} 个）", ""]
        if not group:
            out += ["没有。", ""]
            continue
        for row in group:
            notes = "；".join(note for note in row["notes"])
            out.append(f"- **{row['no']}. {row['name']}**（{row['summary']}）— {notes}")
        out.append("")
    out += [f"## ✅ 保持现状（{len(keep)} 个）", ""]
    by_layer = collections.defaultdict(list)
    for row in keep:
        by_layer[row["layer"]].append(f"{row['no']}. {row['name']}")
    for layer in LAYERS:
        if by_layer[layer]:
            out.append(f"- {layer}：{'、'.join(by_layer[layer])}")
    out += ["", "---", *_how_to_choose(report)]
    return "\n".join(out)


def _how_to_choose(report: dict[str, Any]) -> list[str]:
    """Reply examples built from this report's real row numbers."""
    rows = report["rows"]
    lines = [f"**怎么选**：直接回复序号（本次报告编号 `{report['report_id']}`），例如："]
    deletes = [row["no"] for row in rows if "删" in row["suggestions"]]
    if deletes:
        sample = "、".join(map(str, deletes[:2]))
        lines.append(f"- `删 {sample}`：删除（进回收站，能恢复）；插件会告诉你怎么卸载")
    optimize = next((row["no"] for row in rows if "优化" in row["suggestions"]), None)
    if optimize:
        lines.append(f"- `优化 {optimize}`：我先改一份草稿给你看，你确认后才替换")
    align = next((row["no"] for row in rows if "对齐" in row["suggestions"]), None)
    if align:
        lines.append(f"- `对齐 {align}`：把同名的几份统一成最新的那份")
    if rows:
        lines.append(f"- `{rows[0]['no']} 放到工作流`：调整分层（常驻 / 工作流 / 实验区）")
    lines += ["- `恢复`：从回收站找回", "", "没提到的序号都不会动。"]
    return lines


def checkup_markdown(report: dict[str, Any], previous: dict[str, Any] | None) -> str:
    if not previous:
        return "这是第一次体检，已保存为基准。\n\n" + advice_markdown(report)
    old_paths = {item["path"] for item in previous["inventory"]}
    new_paths = {item["path"] for item in report["inventory"]}
    added = [item["name"] for item in report["inventory"] if item["path"] not in old_paths and item["source"] == USER]
    removed = [item["name"] for item in previous["inventory"] if item["path"] not in new_paths and item["source"] == USER]
    old_notes = {(tuple(row["paths"]), note) for row in previous.get("rows", []) for note in row["notes"]}
    fresh = [row for row in report["rows"] if any((tuple(row["paths"]), note) not in old_notes for note in row["notes"])]
    trial = [row for row in report["rows"] if row["layer"] == TRIAL]
    out = _header(report, "本月 Skills 体检")
    out.append(f"和上次（{previous['generated_at'][:10]}）相比：")
    out.append("")
    if not (added or removed or fresh):
        out.append("没有新变化。")
    if added:
        out.append(f"- 新装了 {len(added)} 个：{'、'.join(added[:15])}")
    if removed:
        out.append(f"- 少了 {len(removed)} 个：{'、'.join(removed[:15])}")
    if fresh:
        out += ["", "**新出现的问题**", "", *_table(fresh, _unit(report))]
    if trial:
        out += ["", f"**实验区（{len(trial)} 个）：这个月留还是删？**", ""]
        out += [f"- {row['no']}. {row['name']}（{row['summary']}）：用过 {_uses(row)} 次" for row in trial]
    out += ["", "---", *_how_to_choose(report)]
    return "\n".join(out)
