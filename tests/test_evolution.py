from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))

import evolution  # noqa: E402
import registry  # noqa: E402
import telemetry  # noqa: E402


def make_skill(root: Path, folder: str, name: str, body: str = "Original.") -> Path:
    path = root / folder
    path.mkdir(parents=True)
    (path / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Test skill\n---\n\n# {name}\n\n{body}\n",
        encoding="utf-8",
    )
    return path


class EvolutionTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = telemetry.initialize_data_dir(self.root / "data", write_locator=False)
        self.skills = self.root / "skills"
        self.skills.mkdir()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def scan(self) -> None:
        registry.scan_registry(self.data, [self.skills.resolve()])

    def evidence(self, name: str) -> Path:
        path = self.root / name
        path.write_text("original output\ncandidate output\nverdict evidence\n", encoding="utf-8")
        return path

    def test_prepare_isolated_candidate_and_reject_protected(self) -> None:
        source = make_skill(self.skills, "writer", "writer")
        make_skill(self.skills / ".system", "core", "core")
        self.scan()
        before = registry.tree_sha256(source)

        prepared = evolution.prepare_candidate(self.data, "writer", None, "Repeated explicit failure")

        self.assertEqual(registry.tree_sha256(source), before)
        self.assertEqual(registry.tree_sha256(Path(prepared["candidate_path"])), before)
        manifest = json.loads(Path(prepared["manifest_path"]).read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "PREPARED")
        with self.assertRaises(SystemExit):
            evolution.prepare_candidate(self.data, "core", None, "Do not touch protected assets")

    def test_gate_requires_real_test_and_paired_majority(self) -> None:
        make_skill(self.skills, "writer", "writer")
        self.scan()
        prepared = evolution.prepare_candidate(self.data, "writer", None, "Improve behavior")
        candidate_id = prepared["candidate_id"]
        candidate = Path(prepared["candidate_path"]) / "SKILL.md"
        candidate.write_text(candidate.read_text(encoding="utf-8") + "\nImproved.\n", encoding="utf-8")

        evolution.record_evaluation(self.data, candidate_id, "deterministic", "PASS", "validator", "syntax", "")
        for judge in ("j1", "j2", "j3"):
            evolution.record_evaluation(
                self.data, candidate_id, "paired", "BETTER", judge, "p1", "",
                self.evidence(f"{judge}.txt"), True,
            )
        with self.assertRaises(SystemExit):
            evolution.promotion_plan(self.data, candidate_id)

        with self.assertRaises(SystemExit):
            evolution.record_evaluation(
                self.data, candidate_id, "full_test", "BETTER", "runner",
                "training-1", "", self.evidence("training.txt"), False,
            )
        evolution.record_evaluation(
            self.data, candidate_id, "full_test", "BETTER", "runner",
            "heldout-1", "", self.evidence("full.txt"), True,
        )
        with self.assertRaises(SystemExit):
            evolution.promotion_plan(self.data, candidate_id)
        evolution.record_proposal(self.data, candidate_id, "Clarify the instruction after repeated failures.")
        plan = evolution.promotion_plan(self.data, candidate_id)
        self.assertEqual(plan["gate"]["status"], "PASS")
        review_diff = Path(plan["review_diff_path"])
        self.assertTrue(review_diff.is_file())
        self.assertIn("+Improved.", review_diff.read_text(encoding="utf-8"))

    def test_tampered_evaluation_evidence_blocks_promotion(self) -> None:
        make_skill(self.skills, "writer", "writer")
        self.scan()
        prepared = evolution.prepare_candidate(self.data, "writer", None, "Improve behavior")
        candidate_id = prepared["candidate_id"]
        candidate_file = Path(prepared["candidate_path"]) / "SKILL.md"
        candidate_file.write_text(candidate_file.read_text(encoding="utf-8") + "\nImproved.\n", encoding="utf-8")
        evolution.record_proposal(self.data, candidate_id, "Clarify the instruction.")
        evolution.record_evaluation(
            self.data, candidate_id, "deterministic", "PASS", "validator", "syntax", ""
        )
        full = evolution.record_evaluation(
            self.data, candidate_id, "full_test", "BETTER", "runner", "heldout-1", "",
            self.evidence("full.txt"), True,
        )
        for judge in ("j1", "j2", "j3"):
            evolution.record_evaluation(
                self.data, candidate_id, "paired", "BETTER", judge, "heldout-1", "",
                self.evidence(f"{judge}.txt"), True,
            )
        Path(full["evidence_path"]).write_text("tampered", encoding="utf-8")

        with self.assertRaises(SystemExit):
            evolution.promotion_plan(self.data, candidate_id)

    def test_candidate_change_invalidates_recorded_evaluations(self) -> None:
        make_skill(self.skills, "writer", "writer")
        self.scan()
        prepared = evolution.prepare_candidate(self.data, "writer", None, "Improve behavior")
        candidate_id = prepared["candidate_id"]
        candidate_file = Path(prepared["candidate_path"]) / "SKILL.md"
        candidate_file.write_text(candidate_file.read_text(encoding="utf-8") + "\nImproved.\n", encoding="utf-8")
        evolution.record_proposal(self.data, candidate_id, "Clarify the instruction.")
        evolution.record_evaluation(
            self.data, candidate_id, "deterministic", "PASS", "validator", "syntax", ""
        )
        for mode, evaluator in [
            ("full_test", "runner"),
            ("paired", "j1"),
            ("paired", "j2"),
            ("paired", "j3"),
        ]:
            evolution.record_evaluation(
                self.data, candidate_id, mode, "BETTER", evaluator, "heldout-1", "",
                self.evidence(f"{evaluator}.txt"), True,
            )
        candidate_file.write_text(candidate_file.read_text(encoding="utf-8") + "\nUntested.\n", encoding="utf-8")
        evolution.record_proposal(self.data, candidate_id, "Clarify the instruction and add an untested rule.")

        with self.assertRaises(SystemExit):
            evolution.promotion_plan(self.data, candidate_id)

    def test_approved_promotion_and_separately_approved_rollback(self) -> None:
        source = make_skill(self.skills, "writer", "writer")
        self.scan()
        original_hash = registry.tree_sha256(source)
        prepared = evolution.prepare_candidate(self.data, "writer", None, "Improve behavior")
        candidate_id = prepared["candidate_id"]
        candidate_file = Path(prepared["candidate_path"]) / "SKILL.md"
        candidate_file.write_text(candidate_file.read_text(encoding="utf-8") + "\nImproved.\n", encoding="utf-8")
        evolution.record_proposal(self.data, candidate_id, "Clarify the instruction.")
        evolution.record_evaluation(
            self.data, candidate_id, "deterministic", "PASS", "validator", "syntax", ""
        )
        for mode, verdict, evaluator in [
            ("full_test", "BETTER", "runner"),
            ("paired", "BETTER", "j1"),
            ("paired", "BETTER", "j2"),
            ("paired", "TIE", "j3"),
        ]:
            evolution.record_evaluation(
                self.data, candidate_id, mode, verdict, evaluator, "heldout-1", "",
                self.evidence(f"{evaluator}.txt"), True,
            )
        plan = evolution.promotion_plan(self.data, candidate_id)
        with self.assertRaises(SystemExit):
            evolution.promotion_execute(self.data, plan["approval_id"], "yes")
        promoted = evolution.promotion_execute(
            self.data, plan["approval_id"], plan["required_user_reply"]
        )
        self.assertNotEqual(registry.tree_sha256(source), original_hash)
        self.assertEqual(registry.tree_sha256(source), promoted["promoted_tree_sha256"])

        rollback = evolution.rollback_plan(self.data, candidate_id)
        evolution.rollback_execute(
            self.data, rollback["approval_id"], rollback["required_user_reply"]
        )
        self.assertEqual(registry.tree_sha256(source), original_hash)


if __name__ == "__main__":
    unittest.main()
