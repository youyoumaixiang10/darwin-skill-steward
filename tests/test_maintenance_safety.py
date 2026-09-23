from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))

from adapters._skill_package import package_claude_plugin, package_skill_zip  # noqa: E402
from darwin_core.models import RuntimeAsset  # noqa: E402
import archive  # noqa: E402
import health  # noqa: E402
import registry  # noqa: E402
import telemetry  # noqa: E402


def make_skill(root: Path, folder: str, content: str) -> Path:
    path = root / folder
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text(content, encoding="utf-8")
    return path


class MaintenanceSafetyTestCase(unittest.TestCase):
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

    def release(self, skill_id: str) -> None:
        scanned = registry.load_json(self.data / "registry.json", {})
        record = next(item for item in scanned["skills"] if item["skill_id"] == skill_id)
        registry.set_runtime_dependency(record, "NOT_REQUIRED")
        telemetry.atomic_write_json(self.data / "registry.json", scanned)

    def test_content_change_after_runtime_release_blocks_archive_plan(self) -> None:
        source = make_skill(self.skills, "old", "---\nname: old\ndescription: Old\n---\n")
        self.scan()
        self.release("old")
        (source / "notes.md").write_text("added after the release was declared", encoding="utf-8")

        with self.assertRaisesRegex(SystemExit, "changed since"):
            archive.archive_plan(self.data, "old", None)
        self.assertTrue(source.exists())

    def test_archive_approval_binds_runtime_and_deployment(self) -> None:
        make_skill(self.skills, "old", "---\nname: old\ndescription: Old\n---\n")
        self.scan()
        self.release("old")
        plan = archive.archive_plan(self.data, "old", None)
        approval = telemetry.load_json(self.data / "approvals" / f"{plan['approval_id']}.json", {})
        self.assertEqual(approval["runtime_id"], "codex")
        self.assertTrue(approval["deployment_id"])
        self.assertEqual(plan["runtime_id"], "codex")
        self.assertEqual(plan["deployment_id"], approval["deployment_id"])

    def test_archived_copy_is_not_a_duplicate_or_replacement_for_the_live_copy(self) -> None:
        content = "---\nname: twin\ndescription: Same\n---\n\nSame body\n"
        make_skill(self.skills, "one", content)
        survivor = make_skill(self.skills, "two", content)
        self.scan()
        scanned = registry.load_json(self.data / "registry.json", {})
        first = next(item for item in scanned["skills"] if item["path"].endswith("one"))
        registry.set_runtime_dependency(first, "NOT_REQUIRED")
        telemetry.atomic_write_json(self.data / "registry.json", scanned)
        plan = archive.archive_plan(self.data, "twin", first["path"])
        archive.archive_execute(self.data, plan["approval_id"], plan["required_user_reply"])
        self.scan()

        report = health.build_report(self.data)
        live = next(item for item in report["skills"] if item["record_id"] != first["record_id"])
        self.assertTrue(survivor.exists())
        self.assertNotIn(live["recommendation"], {"MERGE", "ARCHIVE"})
        self.assertEqual(live["evidence"]["STRUCTURAL"]["overlaps"], [])

    def test_packaging_refuses_to_write_inside_the_live_skill(self) -> None:
        source = make_skill(self.skills, "demo", "---\nname: demo\ndescription: Demo\n---\n")
        before = registry.tree_sha256(source)
        asset = RuntimeAsset(runtime_id="test", native_id="demo", kind="skill", path=str(source))

        for packager in (
            lambda target: package_skill_zip(asset, target),
            lambda target: package_claude_plugin(asset, target, surface="code"),
        ):
            for target in (str(source), str(source / "out"), str(source / "demo.zip")):
                with self.assertRaisesRegex(ValueError, "inside the Skill"):
                    packager(target)
        self.assertEqual(registry.tree_sha256(source), before)


if __name__ == "__main__":
    unittest.main()
