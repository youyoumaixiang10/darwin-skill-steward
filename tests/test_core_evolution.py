from __future__ import annotations

import unittest

from darwin_core.evolution import promotion_gate


class CoreEvolutionTestCase(unittest.TestCase):
    def test_gate_requires_deterministic_and_held_out_better_evidence(self) -> None:
        manifest = {"evaluations": [
            {"mode": "deterministic", "verdict": "PASS"},
            {"mode": "full_test", "verdict": "BETTER", "held_out": True},
            {"mode": "paired", "verdict": "BETTER"},
            {"mode": "paired", "verdict": "BETTER"},
            {"mode": "paired", "verdict": "BETTER"},
        ]}
        self.assertEqual(promotion_gate(manifest)["status"], "PASS")

    def test_gate_rejects_a_non_better_held_out_evaluation(self) -> None:
        manifest = {"evaluations": [
            {"mode": "deterministic", "verdict": "PASS"},
            {"mode": "full_test", "verdict": "SAME", "held_out": True},
            {"mode": "paired", "verdict": "BETTER"},
            {"mode": "paired", "verdict": "BETTER"},
            {"mode": "paired", "verdict": "BETTER"},
        ]}
        self.assertEqual(promotion_gate(manifest)["status"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()

