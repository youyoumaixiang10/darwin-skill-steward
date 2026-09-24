from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))

from adapters._skill_package import RuntimeAsset, frontmatter_fields  # noqa: E402
from darwin_core.frontmatter import parse_frontmatter_file  # noqa: E402
import health  # noqa: E402
import registry  # noqa: E402
import telemetry  # noqa: E402


def write_skill(path: Path, text: str) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    skill_md = path / "SKILL.md"
    skill_md.write_text(text, encoding="utf-8")
    return skill_md


class FrontmatterSafetyTestCase(unittest.TestCase):
    def test_real_yaml_parser_handles_folded_literal_utf8_quotes_and_colons(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            folded = write_skill(
                root / "folded",
                "---\nname: agent-reach\ndescription: >\n  第一行：可以联网。\n  Second line: keeps colon.\n---\n",
            )
            literal = write_skill(
                root / "literal",
                "---\nname: web-access\ndescription: |\n  第一行\n  second: line\ntitle: \"中文: quoted\"\n---\n",
            )

            folded_result = parse_frontmatter_file(folded)
            literal_result = parse_frontmatter_file(literal)

            self.assertEqual(folded_result.status, "VALID")
            self.assertEqual(folded_result.fields["description"], "第一行：可以联网。 Second line: keeps colon.\n")
            self.assertEqual(literal_result.fields["description"], "第一行\nsecond: line\n")
            self.assertEqual(literal_result.fields["title"], "中文: quoted")

    def test_missing_empty_and_invalid_frontmatter_have_distinct_statuses(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            missing = write_skill(root / "missing", "# no frontmatter\n")
            empty = write_skill(root / "empty", "---\n---\n# empty\n")
            invalid = write_skill(root / "invalid", "---\nname: [broken\ndescription: value\n---\n")

            missing_result = parse_frontmatter_file(missing)
            empty_result = parse_frontmatter_file(empty)
            invalid_result = parse_frontmatter_file(invalid)

            self.assertEqual(missing_result.status, "MISSING")
            self.assertEqual(empty_result.status, "EMPTY")
            self.assertEqual(invalid_result.status, "INVALID")
            self.assertEqual(missing_result.missing_required_fields, ("name", "description"))
            self.assertFalse(empty_result.structural_valid)
            self.assertTrue(invalid_result.parse_errors)

    def test_registry_and_packager_share_identical_parse_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            skill_md = write_skill(
                Path(temp) / "shared",
                "---\nname: shared\ndescription: >\n  多行说明\n  with: colon\n---\n",
            )
            asset = RuntimeAsset(
                runtime_id="test",
                native_id="shared",
                kind="skill",
                path=str(skill_md.parent),
                metadata={"skill_md": str(skill_md)},
            )

            self.assertEqual(registry.parse_frontmatter(skill_md), frontmatter_fields(asset))

    def test_missing_required_name_uses_display_fallback_but_is_structurally_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            skill_md = write_skill(
                Path(temp) / "fallback-folder",
                "---\ndescription: Present\n---\n",
            )
            record = registry.build_record(skill_md, discovery_root=skill_md.parent.parent)

            self.assertEqual(record["skill_id"], "fallback-folder")
            self.assertEqual(record["display_name"], "fallback-folder")
            self.assertEqual(record["frontmatter_status"], "VALID")
            self.assertEqual(record["missing_required_fields"], ["name"])
            self.assertFalse(record["structural_valid"])


class DuplicateSafetyTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def record(self, folder: str, *, runtime: str = "codex", asset: str = "ACTIVE_PLUGIN_ASSET") -> dict:
        skill_md = self.root / folder / "SKILL.md"
        record = registry.build_record(skill_md, discovery_root=self.root)
        record["runtime_id"] = runtime
        record["runtime_targets"] = [runtime]
        record["deployment_id"] = runtime
        record["asset_state"] = asset
        return record

    def test_same_skill_md_with_different_assets_is_not_same_tree(self) -> None:
        content = "---\nname: duplicate\ndescription: Same\n---\nBody\n"
        for folder, asset_text in (("one", "one"), ("two", "two")):
            write_skill(self.root / folder, content)
            (self.root / folder / "asset.txt").write_text(asset_text, encoding="utf-8")

        left, right = self.record("one"), self.record("two")
        overlap = health.overlap_map([left, right], 0.82)[left["record_id"]][0]

        self.assertIn("SAME_SKILL_MD", overlap["relations"])
        self.assertNotIn("SAME_TREE", overlap["relations"])
        self.assertEqual(overlap["relation"], "SAME_SKILL_MD")
        self.assertFalse(overlap["cleanup_candidate"])

    def test_complete_identical_trees_are_same_tree(self) -> None:
        content = "---\nname: duplicate\ndescription: Same\n---\nBody\n"
        for folder in ("one", "two"):
            write_skill(self.root / folder, content)
            (self.root / folder / "asset.txt").write_text("same", encoding="utf-8")

        left, right = self.record("one"), self.record("two")
        overlap = health.overlap_map([left, right], 0.82)[left["record_id"]][0]

        self.assertEqual(overlap["relation"], "SAME_TREE")
        self.assertTrue(overlap["cleanup_candidate"])

    def test_cross_runtime_same_tree_is_a_mirror_and_not_a_cleanup_candidate(self) -> None:
        content = "---\nname: duplicate\ndescription: Same\n---\nBody\n"
        for folder in ("codex-copy", "workbuddy-copy"):
            write_skill(self.root / folder, content)

        left = self.record("codex-copy", runtime="codex")
        right = self.record("workbuddy-copy", runtime="workbuddy")
        overlap = health.overlap_map([left, right], 0.82)[left["record_id"]][0]

        self.assertEqual(overlap["relation"], "SAME_TREE")
        self.assertIn("CROSS_RUNTIME_MIRROR", overlap["deployment_flags"])
        self.assertFalse(overlap["cleanup_candidate"])

    def test_protected_same_tree_is_not_a_cleanup_candidate(self) -> None:
        content = "---\nname: duplicate\ndescription: Same\n---\nBody\n"
        for folder in ("user-copy", "protected-copy"):
            write_skill(self.root / folder, content)
        left = self.record("user-copy")
        right = self.record("protected-copy")
        right["protected"] = True
        right["manageable"] = False

        overlap = health.overlap_map([left, right], 0.82)[left["record_id"]][0]

        self.assertEqual(overlap["relation"], "SAME_TREE")
        self.assertFalse(overlap["cleanup_candidate"])

    def test_instruction_similarity_is_inferred_observation_not_merge(self) -> None:
        shared = " ".join(f"shared-token-{index}" for index in range(80))
        write_skill(self.root / "one", f"---\nname: one\ndescription: One\n---\n{shared}\nleft\n")
        write_skill(self.root / "two", f"---\nname: two\ndescription: Two\n---\n{shared}\nright\n")
        left, right = self.record("one"), self.record("two")
        overlap = health.overlap_map([left, right], 0.5)[left["record_id"]][0]
        metrics = {
            "attributed_invocations": 0,
            "known_outcomes": 0,
            "positive": 0,
            "refinement": 0,
            "failure": 0,
            "unknown": 0,
            "failure_rate_known": None,
            "failure_tags": {},
            "last_attributed_invocation": None,
        }
        coverage = {"level": "NONE", "status": "UNKNOWN", "source": None, "since": None}
        recommendation, _ = health.recommendation_for(
            left,
            metrics,
            coverage,
            [overlap],
            {
                "archive_inactivity_days": 90,
                "minimum_known_outcomes": 5,
                "minimum_failures_for_evolve": 3,
                "failure_rate_for_evolve": 0.3,
                "failure_rate_for_keep": 0.2,
            },
            health.dt.datetime.now(health.dt.timezone.utc),
        )

        self.assertEqual(overlap["relation"], "SIMILAR_INSTRUCTIONS")
        self.assertEqual(recommendation, "OBSERVE")

    def test_tree_fingerprint_records_symlink_or_marks_incomplete(self) -> None:
        write_skill(self.root / "linked", "---\nname: linked\ndescription: Link test\n---\n")
        target = self.root / "linked" / "target.txt"
        target.write_text("target", encoding="utf-8")
        link = self.root / "linked" / "link.txt"
        try:
            link.symlink_to(target.name)
        except OSError:
            self.skipTest("Symlink creation is unavailable on this host")

        fingerprint = registry.tree_fingerprint(self.root / "linked")

        self.assertTrue(fingerprint["symlink_detected"])
        self.assertIn("tree_hash_complete", fingerprint)

    def test_scan_records_runtime_scope_root_and_unique_copy(self) -> None:
        home = self.root / "home"
        project = self.root / "project"
        code_root = home / ".codex" / "skills"
        shared_root = home / ".agents" / "skills"
        project_root = project / ".agents" / "skills"
        for root, folder in ((code_root, "code"), (shared_root, "shared"), (project_root, "project")):
            write_skill(root / folder, f"---\nname: {folder}\ndescription: Demo\n---\n")
        data = telemetry.initialize_data_dir(self.root / "data", write_locator=False)

        result = registry.scan_registry(
            data,
            [code_root.resolve(), shared_root.resolve(), project_root.resolve()],
            home=home,
            cwd=project,
        )
        by_name = {item["skill_id"]: item for item in result["skills"]}

        self.assertEqual(by_name["code"]["runtime_id"], "codex")
        self.assertEqual(by_name["shared"]["runtime_id"], "codex")
        self.assertEqual(by_name["shared"]["deployment_id"], "agents_shared")
        self.assertEqual(by_name["shared"]["runtime_targets"], ["codex"])
        self.assertEqual(by_name["project"]["scope"], "project")
        self.assertEqual(by_name["shared"]["origin"], "SHARED_USER")
        self.assertTrue(by_name["code"]["runtime_unique_copy"])
        self.assertEqual(by_name["code"]["discovery_root"], str(code_root.resolve()))

    def test_runtime_release_resets_when_the_skill_tree_changes(self) -> None:
        data = telemetry.initialize_data_dir(self.root / "release-data", write_locator=False)
        skills = self.root / "release-skills"
        skill_md = write_skill(skills / "writer", "---\nname: writer\ndescription: Demo\n---\nBefore\n")
        scanned = registry.scan_registry(data, [skills.resolve()])
        record = scanned["skills"][0]
        registry.set_runtime_dependency(record, "NOT_REQUIRED")
        telemetry.atomic_write_json(data / "registry.json", scanned)

        skill_md.write_text("---\nname: writer\ndescription: Demo\n---\nAfter\n", encoding="utf-8")
        rescanned = registry.scan_registry(data, [skills.resolve()])
        updated = rescanned["skills"][0]

        self.assertEqual(updated["runtime_dependency_status"], "UNKNOWN")
        self.assertNotIn("runtime_dependency_tree_sha256", updated)

    def test_archive_stays_blocked_until_runtime_dependency_is_explicitly_released(self) -> None:
        data = telemetry.initialize_data_dir(self.root / "archive-data", write_locator=False)
        skills = self.root / "archive-skills"
        shared = " ".join(f"shared-token-{index}" for index in range(100))
        old_path = write_skill(skills / "old", f"---\nname: old\ndescription: Old\n---\n{shared}\n")
        new_path = write_skill(skills / "new", f"---\nname: new\ndescription: New\n---\n{shared}\n")
        scanned = registry.scan_registry(data, [skills.resolve()])
        records = {item["skill_id"]: item for item in scanned["skills"]}
        old = (health.dt.datetime.now(health.dt.timezone.utc) - health.dt.timedelta(days=120)).isoformat().replace(
            "+00:00", "Z"
        )
        telemetry.record_event(
            data,
            "skill_invocation",
            {
                "skill_id": "new",
                "record_id": records["new"]["record_id"],
                "turn_id": "used",
                "attribution_source": "MANUAL",
                "attribution_status": "EXPLICIT",
                "outcome": "UNKNOWN",
            },
        )
        telemetry.record_event(
            data,
            "coverage_declared",
            {
                "skill_id": "old",
                "record_id": records["old"]["record_id"],
                "coverage": "COMPLETE",
                "coverage_since": old,
                "coverage_source": "complete export",
                "evidence_status": "EXPLICIT",
            },
        )

        report = health.build_report(data)
        by_name = {item["skill_id"]: item for item in report["skills"]}
        self.assertEqual(by_name["old"]["recommendation"], "OBSERVE")
        self.assertTrue(old_path.exists())
        self.assertTrue(new_path.exists())


if __name__ == "__main__":
    unittest.main()
