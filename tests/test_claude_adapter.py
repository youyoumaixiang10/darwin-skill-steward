from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from adapters.claude import ClaudeCodeAdapter, ClaudeCoworkAdapter


def write_skill(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("---\nname: demo\ndescription: Demo\n---\n", encoding="utf-8")


class ClaudeAdapterTestCase(unittest.TestCase):
    def test_code_discovers_user_and_project_skills(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / "home"
            project = Path(temp) / "project"
            write_skill(home / ".claude" / "skills" / "global" / "SKILL.md")
            write_skill(project / ".claude" / "skills" / "local" / "SKILL.md")
            ids = {asset.native_id for asset in ClaudeCodeAdapter(home=home, cwd=project).discover_assets()}
            self.assertEqual(ids, {"global", "local"})

    def test_code_packages_a_valid_claude_plugin(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_skill(root / "skills" / "demo" / "SKILL.md")
            adapter = ClaudeCodeAdapter(roots=[root / "skills"])
            asset = next(iter(adapter.discover_assets()))
            package = adapter.package_candidate(asset, str(root / "out"))
            with zipfile.ZipFile(package["package_path"]) as archive:
                self.assertIn(".claude-plugin/plugin.json", archive.namelist())
                self.assertIn("skills/demo/SKILL.md", archive.namelist())
                manifest = json.loads(archive.read(".claude-plugin/plugin.json"))
                self.assertEqual(manifest["name"], "darwin-demo")

    def test_cowork_produces_manual_import_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_skill(root / "skills" / "demo" / "SKILL.md")
            adapter = ClaudeCoworkAdapter(roots=[root / "skills"])
            asset = next(iter(adapter.discover_assets()))
            package = adapter.package_candidate(asset, str(root / "out"))
            plan = adapter.prepare_apply({"asset": asset, "package": package})
            self.assertEqual(plan["mode"], "manual_import")
            self.assertFalse(plan["automatic_apply"])


if __name__ == "__main__":
    unittest.main()
