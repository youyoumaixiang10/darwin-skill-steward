from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from adapters.codex import CodexAdapter, _active_plugin_version

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))

import registry


def write_skill(path: Path, *, name: str = "demo") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nname: {name}\ndescription: Demo\n---\n", encoding="utf-8")


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

            self.assertEqual(by_id["writer"].origin, "CODEX_USER")
            self.assertEqual(by_id["demo/skill"].origin, "THIRD_PARTY_PLUGIN")
            self.assertTrue(by_id["writer"].content_sha256)

    def test_distinguishes_shared_user_and_project_agents_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / "home"
            project = Path(temp) / "project"
            write_skill(home / ".agents" / "skills" / "shared" / "SKILL.md", name="shared")
            write_skill(project / ".agents" / "skills" / "project" / "SKILL.md", name="project")

            assets = list(CodexAdapter(home=home, cwd=project, include_plugin_cache=False).discover_assets())
            by_name = {Path(asset.path).name: asset for asset in assets}

            self.assertEqual(by_name["shared"].origin, "SHARED_USER")
            self.assertEqual(by_name["shared"].metadata["scope"], "user")
            self.assertEqual(by_name["shared"].runtime_id, "codex")
            self.assertEqual(by_name["shared"].metadata["deployment_id"], "agents_shared")
            self.assertIn("workbuddy", by_name["shared"].metadata["runtime_targets"])
            self.assertEqual(by_name["project"].origin, "PROJECT")
            self.assertEqual(by_name["project"].metadata["scope"], "project")

    def test_plugin_cache_separates_active_and_inactive_versions_using_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            plugin = home / ".codex" / "plugins" / "cache" / "vendor" / "demo"
            for version in ("1.0.0", "2.0.0"):
                version_root = plugin / version
                write_skill(version_root / "skills" / "writer" / "SKILL.md", name="writer")
                manifest = version_root / ".codex-plugin" / "plugin.json"
                manifest.parent.mkdir(parents=True, exist_ok=True)
                manifest.write_text(
                    '{"name":"demo","version":"' + version + '","author":{"name":"Acme"}}',
                    encoding="utf-8",
                )
            (plugin / ".codex-remote-plugin-install.json").write_text(
                '{"schema_version":1,"active_version":"2.0.0"}', encoding="utf-8"
            )

            assets = list(CodexAdapter(home=home, cwd=home).discover_assets())
            by_version = {asset.metadata["plugin_version"]: asset for asset in assets}

            self.assertEqual(by_version["1.0.0"].metadata["asset_state"], "INACTIVE_CACHED_VERSION")
            self.assertEqual(by_version["2.0.0"].metadata["asset_state"], "ACTIVE_PLUGIN_ASSET")
            self.assertTrue(all(asset.origin == "THIRD_PARTY_PLUGIN" for asset in assets))

    def test_manifest_author_cannot_spoof_official_plugin_origin(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            version_root = home / ".codex" / "plugins" / "cache" / "vendor" / "spoof" / "1.0.0"
            write_skill(version_root / "skills" / "writer" / "SKILL.md", name="writer")
            manifest = version_root / ".codex-plugin" / "plugin.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(
                '{"name":"spoof","version":"1.0.0","author":{"name":"Definitely Not OpenAI"}}',
                encoding="utf-8",
            )

            asset = next(iter(CodexAdapter(home=home, cwd=home).discover_assets()))

            self.assertEqual(asset.origin, "THIRD_PARTY_PLUGIN")
            self.assertEqual(asset.metadata["asset_state"], "CACHED_VERSION_UNKNOWN")

    def test_plain_latest_directory_is_not_activation_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            plugin = Path(temp) / "demo"
            (plugin / "1.0.0").mkdir(parents=True)
            (plugin / "latest").mkdir()

            version, basis = _active_plugin_version(plugin)

            self.assertIsNone(version)
            self.assertEqual(basis, "unresolved")


if __name__ == "__main__":
    unittest.main()

