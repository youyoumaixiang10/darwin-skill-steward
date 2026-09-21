from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class RuntimeCliTestCase(unittest.TestCase):
    def test_doubao_list_package_and_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            skill = root / "exports" / "analyst"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("---\ndescription: Analyst\n---\n", encoding="utf-8")
            script = Path(__file__).resolve().parents[1] / "scripts" / "runtime.py"
            common = [sys.executable, str(script), "--runtime", "doubao", "--root", str(root / "exports")]
            listed = subprocess.run(common + ["list"], check=True, capture_output=True, text=True)
            self.assertEqual(json.loads(listed.stdout)["assets"][0]["native_id"], "analyst")
            packaged = subprocess.run(
                common + ["package", "--asset", "analyst", "--destination", str(root / "out")],
                check=True,
                capture_output=True,
                text=True,
            )
            package_path = json.loads(packaged.stdout)["package"]["package_path"]
            planned = subprocess.run(
                common + ["plan-apply", "--asset", "analyst", "--package", package_path],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertFalse(json.loads(planned.stdout)["automatic_apply"])
            rollback = subprocess.run(
                common + ["plan-rollback", "--asset", "analyst", "--package", package_path],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertFalse(json.loads(rollback.stdout)["automatic_apply"])


if __name__ == "__main__":
    unittest.main()
