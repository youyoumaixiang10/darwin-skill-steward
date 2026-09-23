from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT))

from steward import actions, advisor, render, rows, sources, usage  # noqa: E402

TODAY = dt.date.today()
OLD = (TODAY - dt.timedelta(days=90)).isoformat()


def ts(days_ago: int) -> str:
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")


def write_skill(folder: Path, name: str, description: str, body: str = "Body.", *, age_days: int = 120) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    skill_md = folder / "SKILL.md"
    skill_md.write_text(f"---\nname: {name}\ndescription: {description}\n---\n\n{body}\n", encoding="utf-8")
    stamp = (dt.datetime.now() - dt.timedelta(days=age_days)).timestamp()
    os.utime(skill_md, (stamp, stamp))
    os.utime(folder, (stamp, stamp))
    return folder


def fake_install_date(folder: Path) -> str:
    # Folder creation time cannot be set portably; tests age folders via mtime instead.
    return dt.datetime.fromtimestamp(folder.stat().st_mtime).strftime("%Y-%m-%d")


def jsonl(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(entry, ensure_ascii=False) for entry in entries) + "\n", encoding="utf-8")


def codex_read(skill_dir: Path, when: str) -> dict:
    command = json.dumps({"cmd": f"Get-Content -Raw '{skill_dir / 'SKILL.md'}'"})
    return {"timestamp": when, "type": "response_item", "payload": {"type": "function_call", "name": "shell", "arguments": command}}


def codex_user(text: str, when: str) -> dict:
    return {"timestamp": when, "type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]}}


def claude_skill(name: str, when: str) -> dict:
    return {"timestamp": when, "type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Skill", "input": {"skill": name}}]}}


def claude_user(text: str, when: str) -> dict:
    return {"timestamp": when, "type": "user", "message": {"content": text}}


class StewardTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(sources, "_installed_at", fake_install_date)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.home = Path(self.temp.name) / "home"
        self.store = Path(self.temp.name) / "darwin"
        h = self.home
        # Codex: a built-in, two user Skills, a shared copy, and a noisy system listing.
        write_skill(h / ".codex/skills/.system/skill-creator", "skill-creator", "Create skills")
        self.heavy = write_skill(h / ".codex/skills/copywriting", "copywriting", "Write marketing copy")
        self.unused = write_skill(h / ".codex/skills/old-tool", "old-tool", "An old unused helper")
        write_skill(h / ".agents/skills/shared-thing", "shared-thing", "Shared helper")
        sessions = h / ".codex/sessions/2026/01/01"
        listing = {"timestamp": ts(100), "type": "response_item", "payload": {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": f"{self.unused / 'SKILL.md'}"}]}}
        for index in range(4):
            entries = [listing, codex_read(self.heavy, ts(80 - index)), codex_user("好的", ts(80 - index))]
            if index < 2:
                entries.append(codex_user("这版不对，不是我要的风格", ts(80 - index)))
            jsonl(sessions / f"rollout-{index}.jsonl", entries)
        jsonl(sessions / "rollout-patch.jsonl", [
            {"timestamp": ts(5), "type": "response_item", "payload": {"type": "custom_tool_call", "input": f"*** Begin Patch\n*** Update File: {self.unused / 'SKILL.md'}"}},
        ])
        # Claude Code: user Skills plus a plugin, with usage in transcripts.
        self.claude_copy = write_skill(h / ".claude/skills/copywriting", "copywriting", "Write marketing copy", "Newer body")
        write_skill(h / ".claude/skills/title-maker", "title-maker", "Generate viral titles for WeChat articles and posts quickly")
        write_skill(h / ".claude/skills/headline-maker", "headline-maker", "Generate cover images for WeChat articles and posts fast")
        plugin_path = h / ".claude/plugins/cache/market/finance/1.0"
        write_skill(plugin_path / "skills/comps", "comps", "Comparable companies")
        (h / ".claude/plugins").mkdir(parents=True, exist_ok=True)
        (h / ".claude/plugins/installed_plugins.json").write_text(json.dumps({"version": 2, "plugins": {"finance@market": [{"installPath": str(plugin_path)}]}}), encoding="utf-8")
        jsonl(h / ".claude/projects/p/one.jsonl", [claude_user("start", ts(95)), claude_skill("title-maker", ts(3))])
        # WorkBuddy: usage log with dates.
        write_skill(h / ".workbuddy/skills/wb-used", "wb-used", "Used in WorkBuddy")
        write_skill(h / ".workbuddy/skills/wb-idle", "wb-idle", "Idle in WorkBuddy")
        (h / ".workbuddy/usage-log.json").write_text(json.dumps({
            "version": 1,
            "activeDays": [OLD, TODAY.isoformat()],
            "skills": {"wb-used": {"id": "wb-used", "lastUsedDate": TODAY.isoformat(), "recentDates": [TODAY.isoformat()], "firstSeenDate": OLD}},
        }), encoding="utf-8")
        # Doubao: installed but no usage records.
        write_skill(h / "Doubao/skills/db-skill", "db-skill", "A Doubao skill")
        self.skills = sources.discover_all(self.home)
        self.usage = usage.read_all(self.home)
        self.report = self.finalize(advisor.build_report(self.skills, self.usage))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def finalize(self, report: dict) -> dict:
        rows.finalize(report, self.store)
        actions.save_report(self.store, report)
        return report

    def agent_report(self, agent: str, readers: list[str] | None = None) -> dict:
        found = sources.discover_all(self.home, agents=[agent])
        return self.finalize(advisor.build_report(found, usage.read_all(self.home, readers or [agent]), agent=agent))

    def item(self, kind: str, name: str) -> dict:
        return next(i for i in self.report["items"] if i["kind"] == kind and name in i["title"])

    def row(self, name: str, agent: str | None = None, report: dict | None = None) -> dict:
        report = report or self.report
        return next(r for r in report["rows"] if (r["name"] == name or r.get("plugin") == name) and (agent is None or r["agent"] == agent))

    def test_inventory_marks_sources_for_every_agent(self) -> None:
        found = {(s.agent, s.name): s.source for s in self.skills}
        self.assertEqual(found[("Codex", "skill-creator")], sources.BUILTIN)
        self.assertEqual(found[("Codex", "copywriting")], sources.USER)
        self.assertEqual(found[("Claude Code", "comps")], sources.PLUGIN)
        self.assertEqual(found[("WorkBuddy", "wb-idle")], sources.USER)
        self.assertEqual(found[("豆包", "db-skill")], sources.USER)

    def test_usage_counts_real_use_not_listings_or_edits(self) -> None:
        codex = self.usage["Codex"]
        self.assertEqual(codex.skills["copywriting"].count, 4)
        self.assertEqual(len(codex.skills["copywriting"].rework_sessions), 2)
        self.assertNotIn("old-tool", codex.skills)
        self.assertEqual(self.usage["Claude Code"].skills["title-maker"].count, 1)
        self.assertEqual(self.usage["WorkBuddy"].skills["wb-used"].count, 1)
        self.assertFalse(self.usage["豆包"].available)

    def test_advice_items_carry_reasons(self) -> None:
        idle = self.item("idle", "old-tool")
        self.assertEqual(idle["group"], advisor.KEEP)
        self.assertGreaterEqual(idle["observed_days"], 30)
        optimize = self.item("optimize", "copywriting")
        self.assertIn("不是我要的风格", " ".join(optimize["reasons"]))
        self.assertTrue(any(i["kind"] == "idle_plugin" and i["plugin"] == "finance" for i in self.report["items"]))
        self.assertFalse(any(i["group"] == advisor.DELETE for i in self.report["items"]))
        self.assertFalse(any("skill-creator" in i["title"] for i in self.report["items"]))

    def test_rows_are_numbered_layered_and_explained(self) -> None:
        write_skill(self.home / ".codex/skills/just-installed", "just-installed", "Brand new helper", age_days=2)
        codex = self.agent_report(sources.CODEX)
        numbers = [r["no"] for r in codex["rows"]]
        self.assertEqual(numbers, list(range(1, len(numbers) + 1)))
        self.assertEqual(self.row("just-installed", report=codex)["layer"], rows.TRIAL)
        self.assertNotEqual(self.row("copywriting", report=codex)["layer"], rows.TRIAL)
        self.assertFalse(any(r["name"] == "skill-creator" for r in codex["rows"]))
        text = render.inventory_markdown(codex)
        self.assertIn("| 序号 | Skill | 功能 |", text)
        self.assertIn("## 实验区", text)
        self.assertNotIn("第 1 条", text)

    def test_long_idle_is_flagged_but_not_suggested_for_deletion(self) -> None:
        codex = self.agent_report(sources.CODEX)
        old = self.row("old-tool", report=codex)
        self.assertNotEqual(old["layer"], rows.TRIAL)
        self.assertNotIn("删", old["suggestions"])
        self.assertIn("留着没问题", " ".join(old["notes"]))
        self.assertIn("很久没用", render.advice_markdown(codex))

    def test_duplicate_group_recommends_one_keeper_and_explains_the_rest(self) -> None:
        text = "Explore intent, requirements and design before any creative implementation work"
        keep = write_skill(self.home / ".codex/skills/brainstorm", "brainstorm", text)
        drop = write_skill(self.home / ".codex/skills/superpowers-brainstorm", "superpowers-brainstorm", text)
        sessions = self.home / ".codex/sessions/2026/02/02"
        jsonl(sessions / "rollout-bs.jsonl", [codex_read(keep, ts(10))])
        codex = self.agent_report(sources.CODEX)
        kept, dropped = self.row("brainstorm", report=codex), self.row("superpowers-brainstorm", report=codex)
        self.assertNotIn("删", kept["suggestions"])
        self.assertIn("建议：保留这份", " ".join(kept["notes"]))
        self.assertIn("删", dropped["suggestions"])
        note = " ".join(dropped["notes"])
        self.assertIn(f"保留第 {kept['no']} 行 brainstorm", note)
        self.assertIn("名字只差一个前缀", note)
        self.assertIn("用得最多", note)
        self.assertIn("功能不会少", note)
        self.assertNotIn("留着没问题", note)
        self.assertIn("功能重复，多选一", render.advice_markdown(codex))
        self.assertTrue(drop.exists(), "advice alone must never delete anything")

    def test_similar_skills_with_different_focus_are_never_pick_one(self) -> None:
        write_skill(self.home / ".codex/skills/ian-style", "ian-style", "生成 Ian 风格的中文正文配图，用于文章、帖子、博客、方法论和流程说明")
        write_skill(self.home / ".codex/skills/yoyo-style", "yoyo-style", "生成 Yoyo 风格的中文正文配图，用于文章、帖子、博客、方法论和流程说明")
        codex = self.agent_report(sources.CODEX)
        for name in ("ian-style", "yoyo-style"):
            row = self.row(name, report=codex)
            self.assertNotIn("删", row["suggestions"])
            self.assertIn("🔀", " ".join(row["notes"]))
        self.assertFalse(any(i["kind"] == "duplicate" for i in codex["items"]))

    def test_identical_copies_name_their_locations(self) -> None:
        write_skill(self.home / ".agents/skills/copywriting", "copywriting", "Write marketing copy")
        codex = self.agent_report(sources.CODEX)
        notes = [" ".join(r["notes"]) for r in codex["rows"] if r["name"] == "copywriting"]
        self.assertTrue(any("两份内容完全一样" in n and "Codex 用户目录那份" in n for n in notes), notes)

    def test_layer_override_is_remembered(self) -> None:
        codex = self.agent_report(sources.CODEX)
        number = self.row("old-tool", report=codex)["no"]
        actions.set_layer(self.store, codex, number, rows.RESIDENT)
        again = self.agent_report(sources.CODEX)
        self.assertEqual(self.row("old-tool", report=again)["layer"], rows.RESIDENT)
        with self.assertRaises(actions.ActionError):
            actions.set_layer(self.store, again, number, "随便")

    def test_mirror_and_collision_detection(self) -> None:
        align = self.item("align", "copywriting")
        self.assertEqual(len(align["targets"]), 2)
        collision = self.item("collision", "title-maker")
        self.assertIn("headline-maker", collision["title"])
        claude = self.agent_report(sources.CLAUDE)
        note = " ".join(self.row("title-maker", report=claude)["notes"])
        self.assertIn(f"第 {self.row('headline-maker', report=claude)['no']} 行", note)

    def test_delete_moves_to_recycle_bin_and_restores(self) -> None:
        number = self.row("old-tool")["no"]
        results = actions.delete(self.store, self.report, [number], self.home)
        self.assertFalse(self.unused.exists())
        bin_id = results[0]["bin_id"]
        self.assertEqual(actions.list_bin(self.store)[0]["bin_id"], bin_id)
        actions.restore(self.store, bin_id)
        self.assertTrue((self.unused / "SKILL.md").is_file())
        self.assertEqual(actions.list_bin(self.store), [])

    def test_delete_refuses_changed_content(self) -> None:
        number = self.row("old-tool")["no"]
        (self.unused / "SKILL.md").write_text("changed", encoding="utf-8")
        with self.assertRaisesRegex(actions.ActionError, "被改过"):
            actions.delete(self.store, self.report, [number], self.home)
        self.assertTrue(self.unused.exists())

    def test_builtin_and_outside_paths_are_never_moved(self) -> None:
        builtin = next(s for s in self.skills if s.name == "skill-creator")
        target = {**builtin.as_dict(), "source": sources.USER, "tree_sha256": sources.tree_sha256(Path(builtin.path))}
        with self.assertRaisesRegex(actions.ActionError, "不在用户 Skill 目录"):
            actions._check_movable(target, self.home)
        outside = write_skill(Path(self.temp.name) / "elsewhere/x", "x", "x")
        target = {"name": "x", "path": str(outside), "source": sources.USER, "tree_sha256": sources.tree_sha256(outside)}
        with self.assertRaisesRegex(actions.ActionError, "不在用户 Skill 目录"):
            actions._check_movable(target, self.home)

    def test_plugin_uninstall_is_only_guidance(self) -> None:
        plugin = self.row("finance")
        results = actions.delete(self.store, self.report, [plugin["no"]], self.home)
        self.assertEqual(results[0]["status"], "需要你手动卸载")
        self.assertTrue(Path(plugin["paths"][0]).exists())

    def test_align_replaces_other_copies_recoverably(self) -> None:
        codex_row = self.row("copywriting", sources.CODEX)
        claude_row = self.row("copywriting", sources.CLAUDE)
        actions.align(self.store, self.report, codex_row["no"], claude_row["no"], self.home)
        self.assertEqual(sources.tree_sha256(self.heavy), sources.tree_sha256(self.claude_copy))
        self.assertEqual(len(actions.list_bin(self.store)), 1)
        with self.assertRaisesRegex(actions.ActionError, "没有需要对齐"):
            actions.align(self.store, self.report, self.row("old-tool")["no"], None, self.home)

    def test_draft_edit_diff_and_apply(self) -> None:
        number = self.row("copywriting", sources.CODEX)["no"]
        draft = actions.prepare_draft(self.store, self.report, number, self.home)
        draft_md = Path(draft["copies"][0]["draft_path"]) / "SKILL.md"
        brief = Path(draft["brief"]).read_text(encoding="utf-8")
        self.assertIn("不是我要的风格", brief)
        draft_md.write_text(draft_md.read_text(encoding="utf-8") + "\nKeep the user's voice.\n", encoding="utf-8")
        self.assertIn("Keep the user's voice.", actions.draft_diff(self.store, draft["draft_id"]))
        self.assertNotIn("Keep the user's voice.", (self.heavy / "SKILL.md").read_text(encoding="utf-8"))
        actions.apply_draft(self.store, draft["draft_id"], self.home)
        self.assertIn("Keep the user's voice.", (self.heavy / "SKILL.md").read_text(encoding="utf-8"))
        with self.assertRaisesRegex(actions.ActionError, "已经处理过"):
            actions.apply_draft(self.store, draft["draft_id"], self.home)

    def test_collision_draft_includes_both_skills(self) -> None:
        claude = self.agent_report(sources.CLAUDE)
        draft = actions.prepare_draft(self.store, claude, self.row("title-maker", report=claude)["no"], self.home)
        self.assertEqual({c["name"] for c in draft["copies"]}, {"title-maker", "headline-maker"})

    def test_actions_need_the_exact_report(self) -> None:
        self.assertEqual(actions.parse_numbers("1、3，5-7 9"), [1, 3, 5, 6, 7, 9])
        with self.assertRaises(actions.ActionError):
            actions.parse_numbers("删掉第一个")
        with self.assertRaisesRegex(actions.ActionError, "报告编号"):
            actions.fresh_report(self.store, None)
        with self.assertRaisesRegex(actions.ActionError, "找不到"):
            actions.fresh_report(self.store, "00000000")
        codex = self.agent_report(sources.CODEX)
        with self.assertRaisesRegex(actions.ActionError, "不是 Claude Code 的"):
            actions.fresh_report(self.store, codex["report_id"], sources.CLAUDE)
        stale = {**self.report, "report_id": "abcdef12", "generated_at": (dt.datetime.now() - dt.timedelta(days=8)).isoformat(timespec="seconds")}
        actions.save_report(self.store, stale)
        with self.assertRaisesRegex(actions.ActionError, "超过"):
            actions.fresh_report(self.store, "abcdef12")

    def test_report_covers_only_the_current_agent(self) -> None:
        claude = self.agent_report(sources.CLAUDE)
        self.assertEqual({row["agent"] for row in claude["inventory"]}, {sources.CLAUDE})
        self.assertEqual(set(claude["coverage"]), {sources.CLAUDE})
        self.assertFalse(any(target["agent"] != sources.CLAUDE for item in claude["items"] for target in item["targets"]))
        self.assertFalse(any(item["kind"] == "align" for item in claude["items"]))
        text = render.inventory_markdown(claude)
        self.assertIn("Claude Code 的 Skills 盘点", text)
        self.assertNotIn("WorkBuddy", text)

    def test_same_agent_copies_are_still_aligned(self) -> None:
        write_skill(self.home / ".agents/skills/copywriting", "copywriting", "Write marketing copy", "Old shared body")
        codex = self.agent_report(sources.CODEX, [sources.CODEX, sources.WORKBUDDY])
        align = next(item for item in codex["items"] if item["kind"] == "align")
        self.assertEqual({t["location"] for t in align["targets"]}, {"Codex 用户目录", "共享目录 .agents"})
        self.assertIn("建议：对齐", " ".join(self.row("copywriting", report=codex)["notes"]))

    def test_agent_detection(self) -> None:
        self.assertEqual(sources.resolve_agent(None, {"CLAUDECODE": "1"}), sources.CLAUDE)
        self.assertEqual(sources.resolve_agent(None, {"CODEBUDDY_NODE_BIN": "x"}), sources.WORKBUDDY)
        self.assertEqual(sources.resolve_agent(None, {"CODEX_THREAD_ID": "x"}), sources.CODEX)
        self.assertIsNone(sources.resolve_agent(None, {"CODEX_HOME": "x"}))
        self.assertEqual(sources.resolve_agent("claude", {}), sources.CLAUDE)
        with self.assertRaises(ValueError):
            sources.resolve_agent("chatgpt", {})

    def test_cli_runs_per_agent_and_acts_on_the_named_report(self) -> None:
        import contextlib
        import io
        sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
        import darwin as cli

        os.environ["DARWIN_HOME"] = str(self.store)
        try:
            outputs = {}
            for agent in ("codex", "workbuddy"):
                buffer = io.StringIO()
                with contextlib.redirect_stdout(buffer):
                    self.assertEqual(cli.main(["--agent", agent, "--user-home", str(self.home), "inventory"]), 0)
                outputs[agent] = buffer.getvalue()
            self.assertIn("Codex 的 Skills 盘点", outputs["codex"])
            self.assertNotIn("wb-idle", outputs["codex"])
            self.assertIn("wb-idle", outputs["workbuddy"])
            codex_report = actions.load_report(self.store, agent=sources.CODEX)
            number = str(self.row("old-tool", report=codex_report)["no"])
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(cli.main(["--agent", "codex", "--user-home", str(self.home), "delete", number]), 2)
            self.assertTrue(self.unused.exists())
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(["--agent", "codex", "--user-home", str(self.home), "--report", codex_report["report_id"], "delete", number]), 0)
            self.assertFalse(self.unused.exists())
        finally:
            os.environ.pop("DARWIN_HOME", None)

    def test_hash_in_description_is_flagged_and_explained(self) -> None:
        folder = self.home / ".claude/skills/orange"
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text("---\nname: orange\ndescription: 橙字 #ff5722 排版，用户说排版时触发\n---\nbody\n", encoding="utf-8")
        skill = sources.build_skill(sources.CLAUDE, folder, sources.USER, "Claude 用户目录")
        self.assertEqual(skill.description, "橙字")
        self.assertIn("description 被 # 截断", skill.problems)
        report = self.finalize(advisor.build_report([skill], usage.read_all(self.home, [sources.CLAUDE]), agent=sources.CLAUDE))
        text = render.inventory_markdown(report)
        self.assertIn("# 后面的内容被当成注释丢掉了", text)
        self.assertIn("建议：优化", text)
        self.assertNotIn("格式有问题", text)

    def test_notes_explain_plugin_twins(self) -> None:
        write_skill(self.home / ".claude/skills/comps", "comps", "Comparable companies copy")
        claude = self.agent_report(sources.CLAUDE)
        plugin = self.row("finance", report=claude)
        note = " ".join(self.row("comps", report=claude)["notes"])
        self.assertIn(f"和第 {plugin['no']} 行插件 finance 里的 comps 重名", note)

    def test_install_date_ignores_old_file_times_from_copies(self) -> None:
        mock.patch.stopall()
        folder = self.home / ".workbuddy/skills/fresh-copy"
        folder.mkdir(parents=True)
        skill_md = folder / "SKILL.md"
        skill_md.write_text("---\nname: fresh-copy\ndescription: copied\n---\n", encoding="utf-8")
        old = (dt.datetime.now() - dt.timedelta(days=120)).timestamp()
        os.utime(skill_md, (old, old))
        self.assertEqual(sources._installed_at(folder), dt.date.today().isoformat())

    def test_missing_pyyaml_stops_with_a_clear_message(self) -> None:
        import builtins
        import contextlib
        import io
        sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
        import darwin as cli

        real_import = builtins.__import__

        def no_yaml(name, *args, **kwargs):
            if name == "yaml":
                raise ImportError("no yaml")
            return real_import(name, *args, **kwargs)

        errors = io.StringIO()
        with mock.patch("builtins.__import__", no_yaml), contextlib.redirect_stderr(errors):
            self.assertEqual(cli.main(["--agent", "codex", "inventory"]), 2)
        self.assertIn("PyYAML", errors.getvalue())

    def test_summary_cache_round_trip(self) -> None:
        from steward import summaries

        entries = [{"key": summaries.summary_key("copywriting", "Write marketing copy"), "name": "copywriting", "description": "Write marketing copy", "needs_layer": True}]
        todo = summaries.todo(entries, summaries.load(self.store))
        self.assertEqual(todo[0]["need"], "summary+layer")
        summaries.save(self.store, {todo[0]["key"]: "写营销文案", "bad key": "x"})
        self.assertEqual(len(summaries.todo(entries, summaries.load(self.store))), 1)
        summaries.save(self.store, {todo[0]["key"]: {"summary": "写营销文案", "layer": "工作流"}})
        self.assertEqual(summaries.todo(entries, summaries.load(self.store)), [])
        self.assertEqual(summaries.lookup(summaries.load(self.store), todo[0]["key"]), ("写营销文案", "工作流"))
        self.assertEqual(summaries.fallback(""), "（没有写简介）")

    def test_checkup_reports_changes_and_asks_about_trial(self) -> None:
        write_skill(self.home / ".codex/skills/trial-one", "trial-one", "Something to try", age_days=3)
        codex = self.agent_report(sources.CODEX)
        text = render.checkup_markdown(codex, codex)
        self.assertIn("没有新变化", text)
        self.assertIn("这个月留还是删", text)
        write_skill(self.home / ".codex/skills/brand-new", "brand-new", "Something new", age_days=1)
        fresh = self.agent_report(sources.CODEX)
        self.assertIn("brand-new", render.checkup_markdown(fresh, codex))
        self.assertIn("Codex 的 Skills 优化建议", render.advice_markdown(fresh))


if __name__ == "__main__":
    unittest.main()
