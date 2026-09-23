#!/usr/bin/env python3
"""Darwin Skill steward: inventory, advice, and recoverable actions in one CLI.

  darwin.py inventory [--full]     list every Skill with source and usage
  darwin.py advise                 numbered delete / optimize / keep advice
  darwin.py checkup                only what changed since the last report
  darwin.py delete 1、3、5-8        move chosen Skills to the recycle bin
  darwin.py align 59 [--use 2]     make every copy match one version
  darwin.py draft 83               copy a Skill into an editable draft
  darwin.py diff <draft-id>        show draft changes
  darwin.py apply-draft <draft-id> replace the Skill with the draft
  darwin.py bin                    list the recycle bin
  darwin.py restore <bin-id>       put a recycled Skill back
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from steward import actions, advisor, render, rows, sources, summaries, usage  # noqa: E402


def build(args: argparse.Namespace, agent: str) -> dict:
    home = Path(args.user_home).expanduser() if args.user_home else None
    skills = sources.discover_all(home, [Path(value) for value in args.doubao_root], agents=[agent])
    # Codex's shared .agents folder may also serve WorkBuddy; read its log to protect those Skills.
    readers = [agent, sources.WORKBUDDY] if agent == sources.CODEX else [agent]
    report = advisor.build_report(skills, usage.read_all(home, readers), agent=agent)
    return rows.finalize(report, actions.darwin_home())


def emit(args: argparse.Namespace, markdown: str, data: object) -> None:
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(markdown)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Darwin Skill steward")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    parser.add_argument("--agent", help="codex / claude / workbuddy / doubao (default: the Agent running this command)")
    parser.add_argument("--report", help="report id shown at the top of the table; required for delete / align / draft / layer")
    parser.add_argument("--doubao-root", action="append", default=[], help="extra exported Doubao Skill folder")
    parser.add_argument("--user-home", help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True)
    inventory = sub.add_parser("inventory")
    inventory.add_argument("--full", action="store_true")
    sub.add_parser("advise")
    summary = sub.add_parser("summaries", help="list Skills that still need a Chinese one-line summary, or save them")
    summary.add_argument("--save", help="JSON file mapping key to summary")
    sub.add_parser("checkup")
    delete = sub.add_parser("delete")
    delete.add_argument("numbers", nargs="+")
    align = sub.add_parser("align")
    align.add_argument("number", type=int)
    align.add_argument("--use", type=int)
    draft = sub.add_parser("draft")
    draft.add_argument("number", type=int)
    diff = sub.add_parser("diff")
    diff.add_argument("draft_id")
    apply = sub.add_parser("apply-draft")
    apply.add_argument("draft_id")
    layer = sub.add_parser("layer", help="move a row to 常驻 / 工作流 / 实验区")
    layer.add_argument("number", type=int)
    layer.add_argument("layer")
    sub.add_parser("bin")
    restore = sub.add_parser("restore")
    restore.add_argument("bin_id")
    args = parser.parse_args(argv)

    store = actions.darwin_home()
    user_home = Path(args.user_home).expanduser() if args.user_home else None
    try:
        try:
            agent = sources.resolve_agent(args.agent)
        except ValueError as exc:
            raise actions.ActionError(str(exc)) from exc
        if agent is None and args.command not in {"diff", "apply-draft", "bin", "restore"}:
            raise actions.ActionError("认不出当前是哪个 Agent，请加上 --agent codex / claude / workbuddy / doubao。")
        if args.command == "summaries":
            if args.save:
                try:
                    updates = json.loads(Path(args.save).read_text(encoding="utf-8"))
                except (OSError, ValueError) as exc:
                    raise actions.ActionError(f"读不了摘要文件：{exc}") from exc
                count = summaries.save(store, updates if isinstance(updates, dict) else {})
                emit(args, f"已保存 {count} 条功能说明。", {"saved": count})
            else:
                home = Path(args.user_home).expanduser() if args.user_home else None
                found = [skill.as_dict() for skill in sources.discover_all(home, [Path(v) for v in args.doubao_root], agents=[agent])]
                print(json.dumps(summaries.todo(summaries.entries_for(found), summaries.load(store)), ensure_ascii=False, indent=2))
            return 0
        if args.command in {"inventory", "advise", "checkup"}:
            previous = actions.load_report(store, agent=agent) if args.command == "checkup" else None
            report = build(args, agent)
            actions.save_report(store, report)
            if args.command == "inventory":
                emit(args, render.inventory_markdown(report, args.full), report)
            elif args.command == "advise":
                emit(args, render.advice_markdown(report), report)
            else:
                emit(args, render.checkup_markdown(report, previous), report)
        elif args.command == "delete":
            report = actions.fresh_report(store, args.report, agent)
            numbers = actions.parse_numbers(" ".join(args.numbers))
            results = actions.delete(store, report, numbers, user_home)
            lines = []
            for r in results:
                detail = f"（回收站编号 {r['bin_id']}）" if r.get("bin_id") else f"：{r.get('steps', '')}"
                lines.append(f"- {r['no']}. {r['name']}（{r['agent']}）{r['status']}{detail}")
            emit(args, "\n".join(lines), results)
        elif args.command == "align":
            report = actions.fresh_report(store, args.report, agent)
            results = actions.align(store, report, args.number, args.use, user_home)
            emit(args, "\n".join(f"- {r['name']}（{r['location']}）{r['status']}，旧版本在回收站 {r['bin_id']}" for r in results), results)
        elif args.command == "layer":
            report = actions.fresh_report(store, args.report, agent)
            result = actions.set_layer(store, report, args.number, args.layer)
            emit(args, f"已把 {result['name']} 放到{result['layer']}，下次盘点生效。", result)
        elif args.command == "draft":
            report = actions.fresh_report(store, args.report, agent)
            result = actions.prepare_draft(store, report, args.number, user_home)
            text = [f"草稿 {result['draft_id']} 已准备好，说明见 {result['brief']}", *[f"- 编辑：{c['draft_path']}" for c in result["copies"]]]
            emit(args, "\n".join(text), result)
        elif args.command == "diff":
            text = actions.draft_diff(store, args.draft_id)
            emit(args, text or "草稿还没有任何改动。", {"diff": text})
        elif args.command == "apply-draft":
            results = actions.apply_draft(store, args.draft_id, user_home)
            emit(args, "\n".join(f"- {r['name']}（{r['agent']}）{r['status']}，旧版本在回收站 {r['bin_id']}" for r in results), results)
        elif args.command == "bin":
            entries = actions.list_bin(store)
            text = "\n".join(f"- {e['bin_id']}：{e['name']}（{e['agent']}）{e['recycled_at']} 原因 {e['reason']}" for e in entries)
            emit(args, text or "回收站是空的。", entries)
        elif args.command == "restore":
            result = actions.restore(store, args.bin_id)
            emit(args, f"{result['name']}（{result['agent']}）已恢复到 {result['path']}", result)
    except actions.ActionError as exc:
        print(f"没有执行：{exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
