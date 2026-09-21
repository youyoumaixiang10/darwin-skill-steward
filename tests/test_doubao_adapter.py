from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from adapters.doubao import DoubaoAdapter
from darwin_core.models import CapabilityUnavailable


class DoubaoAdapterTestCase(unittest.TestCase):
    def test_requires_explicit_export_root_and_builds_reviewed_import(self) -> None:
        self.assertEqual(list(DoubaoAdapter().discover_assets()), [])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            skill = root / "exports" / "analyst"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("---\ndescription: Analyst\n---\n", encoding="utf-8")
            adapter = DoubaoAdapter(roots=[root / "exports"])
            asset = next(iter(adapter.discover_assets()))
            package = adapter.package_candidate(asset, str(root / "out"))
            with zipfile.ZipFile(package["package_path"]) as archive:
                self.assertIn("analyst/SKILL.md", archive.namelist())
            plan = adapter.prepare_apply({"asset": asset, "package": package})
            self.assertFalse(plan["public_automatic_install_api"])
            self.assertIsInstance(adapter.observe({}), CapabilityUnavailable)


if __name__ == "__main__":
    unittest.main()
