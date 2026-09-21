from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from adapters.workbuddy import WorkBuddyAdapter


class WorkBuddyAdapterTestCase(unittest.TestCase):
    def test_discovers_and_packages_standard_skill_zip(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            skill = root / ".agents" / "skills" / "writer"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(
                "---\nname: writer\ndescription: Writer\ndescription_zh: 写作\ndescription_en: Writer\nversion: 1.0.0\nauthor: Test\n---\n",
                encoding="utf-8",
            )
            adapter = WorkBuddyAdapter(home=root, cwd=root)
            asset = next(iter(adapter.discover_assets()))
            package = adapter.package_candidate(asset, str(root / "out"))
            with zipfile.ZipFile(package["package_path"]) as archive:
                self.assertIn("writer/SKILL.md", archive.namelist())
            plan = adapter.prepare_apply({"asset": asset, "package": package})
            self.assertFalse(plan["automatic_apply"])

    def test_rejects_package_missing_required_workbuddy_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            skill = root / "skills" / "writer"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("---\ndescription: Writer\n---\n", encoding="utf-8")
            adapter = WorkBuddyAdapter(roots=[root / "skills"])
            asset = next(iter(adapter.discover_assets()))
            with self.assertRaisesRegex(ValueError, "description_zh"):
                adapter.package_candidate(asset, str(root / "out"))


if __name__ == "__main__":
    unittest.main()
