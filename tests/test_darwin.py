from __future__ import annotations

import concurrent.futures
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PLUGIN_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import archive  # noqa: E402
import health  # noqa: E402
import observe  # noqa: E402
import registry  # noqa: E402
import telemetry  # noqa: E402


def make_skill(root: Path, folder: str, name: str, description: str, body: str = "Do the task.") -> Path:
    path = root / folder
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n\n{body}\n",
        encoding="utf-8",
    )
    return path


class DarwinTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = telemetry.initialize_data_dir(self.root / "data", write_locator=False)
        self.skills = self.root / "skills"
        self.skills.mkdir()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def scan(self) -> dict:
        return registry.scan_registry(self.data, [self.skills.resolve()])

    def test_hook_events_stay_unknown_and_evidence_is_redacted(self) -> None:
        with mock.patch.dict(os.environ, {"DARWIN_DATA_DIR": str(self.data)}, clear=False):
            observe.observe(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "s1",
                    "turn_id": "t1",
                    "prompt": "email me at me@example.com with sk-abcdefghijklmnop",
                    "cwd": str(self.root),
                    "model": "test",
                }
            )
            observe.observe(
                {
                    "hook_event_name": "Stop",
                    "session_id": "s1",
                    "turn_id": "t1",
                    "last_assistant_message": "done",
                    "cwd": str(self.root),
                    "model": "test",
                }
            )
        events = telemetry.iter_events(self.data)
        self.assertEqual([item["outcome"] for item in events], ["UNKNOWN", "UNKNOWN"])
        prompt_event = next(item for item in events if item["event_type"] == "prompt_submitted")
        evidence = json.loads((self.data / prompt_event["evidence_ref"]).read_text(encoding="utf-8"))
        self.assertNotIn("me@example.com", evidence["text"])
        self.assertNotIn("sk-abcdefghijklmnop", evidence["text"])
        self.assertIn("[REDACTED_EMAIL]", evidence["text"])

    @unittest.skipUnless(os.name == "nt", "Windows Hook launcher test")
    def test_windows_hook_launcher_passes_real_process_stdin(self) -> None:
        env = os.environ.copy()
        env["PLUGIN_ROOT"] = str(PLUGIN_ROOT)
        env["PLUGIN_DATA"] = str(self.data)
        payload = json.dumps(
            {
                "hook_event_name": "Stop",
                "session_id": "launcher-session",
                "turn_id": "launcher-turn",
                "cwd": str(self.root),
                "model": "test",
                "last_assistant_message": "launcher result",
            }
        )
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                "& (Join-Path $env:PLUGIN_ROOT 'scripts\\run-observer.ps1')",
            ],
            input=payload,
            text=True,
            capture_output=True,
            env=env,
            timeout=15,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "{}")
        events = telemetry.iter_events(self.data)
        self.assertEqual(events[0]["event_type"], "turn_stopped")
        self.assertEqual(events[0]["outcome"], "UNKNOWN")

    def test_concurrent_writes_remain_readable(self) -> None:
        def write(index: int) -> None:
            telemetry.record_event(self.data, "concurrent_test", {"index": index})

        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
            list(pool.map(write, range(120)))
        events = telemetry.iter_events(self.data)
        self.assertEqual(len(events), 120)
        self.assertEqual({item["index"] for item in events}, set(range(120)))

    def test_registry_protects_system_skills(self) -> None:
        make_skill(self.skills, "user-skill", "user-skill", "User capability")
        make_skill(self.skills / ".system", "system-skill", "system-skill", "System capability")
        result = self.scan()
        by_name = {item["skill_id"]: item for item in result["skills"]}
        self.assertTrue(by_name["user-skill"]["manageable"])
        self.assertFalse(by_name["user-skill"]["protected"])
        self.assertTrue(by_name["system-skill"]["protected"])
        self.assertEqual(by_name["system-skill"]["origin"], "SYSTEM")

    def test_missing_telemetry_cannot_trigger_archive(self) -> None:
        make_skill(self.skills, "annual", "annual", "Annual review capability")
        result = self.scan()
        old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=200)).isoformat().replace("+00:00", "Z")
        result["skills"][0]["first_seen_at"] = old
        telemetry.atomic_write_json(self.data / "registry.json", result)
        report = health.build_report(self.data)
        self.assertEqual(report["skills"][0]["recommendation"], "OBSERVE")
        self.assertEqual(report["skills"][0]["coverage"]["level"], "NONE")

    def test_archive_recommendation_needs_dated_complete_coverage_and_replacement(self) -> None:
        repeated = " ".join(f"shared-token-{index}" for index in range(100))
        old = make_skill(self.skills, "old-title", "old-title", "Marketing title workflow", repeated)
        new = make_skill(self.skills, "new-title", "new-title", "Marketing title workflow improved", repeated)
        result = self.scan()
        records = {item["skill_id"]: item for item in result["skills"]}
        telemetry.record_event(
            self.data,
            "skill_invocation",
            {
                "skill_id": "new-title",
                "record_id": records["new-title"]["record_id"],
                "turn_id": "replacement-used",
                "attribution_source": "MANUAL",
                "attribution_status": "EXPLICIT",
                "outcome": "UNKNOWN",
            },
        )
        since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=120)).isoformat().replace("+00:00", "Z")
        telemetry.record_event(
            self.data,
            "coverage_declared",
            {
                "skill_id": "old-title",
                "record_id": records["old-title"]["record_id"],
                "coverage": "COMPLETE",
                "coverage_since": since,
                "coverage_source": "test complete export",
                "evidence_status": "EXPLICIT",
            },
        )
        report = health.build_report(self.data)
        recommendations = {item["skill_id"]: item["recommendation"] for item in report["skills"]}
        self.assertEqual(recommendations["old-title"], "ARCHIVE")
        self.assertNotEqual(recommendations["new-title"], "ARCHIVE")

    def test_repeated_explicit_failures_can_recommend_evolve(self) -> None:
        make_skill(self.skills, "title", "title", "Generate titles")
        self.scan()
        for index, outcome in enumerate(["FAILURE", "FAILURE", "FAILURE", "POSITIVE", "POSITIVE", "REFINEMENT"]):
            turn = f"t{index}"
            telemetry.record_event(
                self.data,
                "skill_invocation",
                {
                    "skill_id": "title",
                    "turn_id": turn,
                    "attribution_source": "MANUAL",
                    "attribution_status": "EXPLICIT",
                    "outcome": "UNKNOWN",
                },
            )
            telemetry.record_event(
                self.data,
                "outcome",
                {
                    "skill_id": "title",
                    "turn_id": turn,
                    "outcome": outcome,
                    "outcome_status": "EXPLICIT",
                    "failure_tag": "repetitive" if outcome == "FAILURE" else None,
                },
            )
        report = health.build_report(self.data)
        item = report["skills"][0]
        self.assertEqual(item["recommendation"], "EVOLVE")
        self.assertEqual(item["metrics"]["unknown"], 0)
        self.assertEqual(item["evidence"]["HUMAN"]["status"], "EXPLICIT")
        self.assertEqual(item["evidence"]["EXPERIMENTAL"]["status"], "UNKNOWN")

    def test_exact_duplicates_recommend_merge_not_archive(self) -> None:
        content = "---\nname: duplicate\ndescription: Same\n---\n\nSame body\n"
        for folder in ("one", "two"):
            target = self.skills / folder
            target.mkdir()
            (target / "SKILL.md").write_text(content, encoding="utf-8")
        self.scan()
        report = health.build_report(self.data)
        self.assertEqual({item["recommendation"] for item in report["skills"]}, {"MERGE"})
        self.assertTrue(all(item["evidence"]["STRUCTURAL"]["overlaps"] for item in report["skills"]))

    def test_ambiguous_skill_name_does_not_share_name_only_telemetry(self) -> None:
        make_skill(self.skills, "one", "same-name", "First")
        make_skill(self.skills, "two", "same-name", "Second", "Different body")
        self.scan()
        telemetry.record_event(
            self.data,
            "skill_invocation",
            {
                "skill_id": "same-name",
                "turn_id": "t1",
                "attribution_source": "MANUAL",
                "attribution_status": "EXPLICIT",
                "outcome": "UNKNOWN",
            },
        )
        report = health.build_report(self.data)
        self.assertTrue(all(item["ambiguous_name"] for item in report["skills"]))
        self.assertTrue(all(item["metrics"]["attributed_invocations"] == 0 for item in report["skills"]))

    def test_archive_requires_exact_approval_and_is_reversible(self) -> None:
        source = make_skill(self.skills, "old", "old", "Old disposable skill")
        self.scan()
        plan = archive.archive_plan(self.data, "old", None)
        with self.assertRaises(SystemExit):
            archive.archive_execute(self.data, plan["approval_id"], "yes")
        self.assertTrue(source.exists())

        result = archive.archive_execute(self.data, plan["approval_id"], plan["required_user_reply"])
        self.assertFalse(source.exists())
        self.assertTrue(Path(result["archive_path"]).exists())

        restore_plan = archive.restore_plan(self.data, result["archive_id"])
        restored = archive.restore_execute(
            self.data, restore_plan["approval_id"], restore_plan["required_user_reply"]
        )
        self.assertTrue(source.exists())
        self.assertEqual(registry.tree_sha256(source), registry.tree_sha256(Path(restored["path"])))

    def test_target_change_invalidates_archive_approval(self) -> None:
        source = make_skill(self.skills, "mutable", "mutable", "Mutable skill")
        self.scan()
        plan = archive.archive_plan(self.data, "mutable", None)
        (source / "note.txt").write_text("changed", encoding="utf-8")
        with self.assertRaises(SystemExit):
            archive.archive_execute(self.data, plan["approval_id"], plan["required_user_reply"])
        self.assertTrue(source.exists())

    def test_scan_preserves_archived_record_for_restore(self) -> None:
        make_skill(self.skills, "old", "old", "Old disposable skill")
        self.scan()
        plan = archive.archive_plan(self.data, "old", None)
        result = archive.archive_execute(self.data, plan["approval_id"], plan["required_user_reply"])
        rescanned = self.scan()
        archived = [item for item in rescanned["skills"] if item["skill_id"] == "old"]
        self.assertEqual(len(archived), 1)
        self.assertEqual(archived[0]["status"], "ARCHIVED")
        restore_plan = archive.restore_plan(self.data, result["archive_id"])
        archive.restore_execute(self.data, restore_plan["approval_id"], restore_plan["required_user_reply"])
        self.assertTrue((self.skills / "old").exists())

    def test_no_permanent_delete_command(self) -> None:
        parser = archive.build_parser()
        with mock.patch("sys.stderr"):
            with self.assertRaises(SystemExit):
                parser.parse_args(["delete"])

    def test_required_project_files_exist(self) -> None:
        required = [
            ".codex-plugin/plugin.json",
            "hooks/hooks.json",
            "skills/darwin/SKILL.md",
            "scripts/observe.py",
            "scripts/telemetry.py",
            "scripts/registry.py",
            "scripts/health.py",
            "scripts/archive.py",
            "schemas/event.schema.json",
            "README.md",
            "ACCEPTANCE.md",
        ]
        self.assertEqual([value for value in required if not (PLUGIN_ROOT / value).is_file()], [])


if __name__ == "__main__":
    unittest.main()
