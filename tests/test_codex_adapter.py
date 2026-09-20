from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from adapters.codex import CodexAdapter

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))

import registry


def write_skill(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("---\nname: demo\n---\n", encoding="utf-8")


class CodexAdapterTestCase(unittest.TestCase):
    def test_registry_roots_match_codex_adapter_when_no_explicit_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            write_skill(home / ".codex" / "skills" / "writer" / "SKILL.md")
            roots = registry.discover_roots(home, [], False, home=home)
            self.assertEqual(roots, CodexAdapter(home=home, cwd=home, include_plugin_cache=False).discovery_roots())

    def test_discovers_user_and_plugin_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            write_skill(home / ".codex" / "skills" / "writer" / "SKILL.md")
            write_skill(home / ".codex" / "plugins" / "cache" / "demo" / "skill" / "SKILL.md")

            assets = list(CodexAdapter(home=home, cwd=home).discover_assets())
            by_id = {asset.native_id: asset for asset in assets}

            self.assertEqual(by_id["writer"].origin, "user")
            self.assertEqual(by_id["demo/skill"].origin, "plugin")
            self.assertTrue(by_id["writer"].content_sha256)


if __name__ == "__main__":
    unittest.main()

