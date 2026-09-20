# Controlled Skill Evolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Add a tested, reversible candidate-to-promotion lifecycle to Darwin for Codex.

**Architecture:** A new `evolution.py` owns candidate manifests, evaluation evidence, promotion approvals, source snapshots, and rollback. Existing registry, hashing, event storage, and approval primitives are reused. The Darwin Skill orchestrates model-written candidate edits while the script enforces deterministic safety gates.

**Tech Stack:** Python 3 standard library, unittest, JSON files, Codex Skill instructions.

## Global Constraints

- Never edit a live Skill before exact promotion approval.
- Never treat UNKNOWN, INFERRED, dry-run, or judge-only evidence as a successful real-world validation.
- Protect system, official, plugin-bundled, symlinked, and out-of-root Skills.
- Promotion and rollback are reversible and separately approved.

---

### Task 1: Candidate preparation

**Files:**
- Create: `scripts/evolution.py`
- Modify: `tests/test_darwin.py`

**Interfaces:**
- Produces: `prepare_candidate(data_dir, skill_name, skill_path, reason) -> dict`
- Persists: `evolution/<candidate-id>/manifest.json`, `baseline/`, and `candidate/`

- [ ] Write tests proving protected targets are rejected and source content is unchanged.
- [ ] Run the new tests and confirm they fail because `evolution` does not exist.
- [ ] Implement target validation, isolated copies, hashes, manifest creation, and a `candidate_prepared` event.
- [ ] Run the tests and confirm they pass.

### Task 2: Evaluation gate and promotion

**Files:**
- Modify: `scripts/evolution.py`
- Modify: `tests/test_darwin.py`
- Modify: `schemas/approval.schema.json`

**Interfaces:**
- Produces: `record_proposal(...)`, `record_evaluation(...)`, `promotion_gate(manifest)`, `promotion_plan(...)`, and `promotion_execute(...)`
- Gate: deterministic PASS, full_test BETTER, and strict paired BETTER majority with at least three evaluators

- [ ] Write tests proving dry-run-only, judge-only, deterministic failure, full-test regression, and tied paired votes cannot promote.
- [ ] Run the tests and confirm the missing gate fails.
- [ ] Implement proposal recording, evidence-backed evaluation records, and the exact gate.
- [ ] Write tests for exact approval, source-hash recheck, candidate-hash recheck, snapshot creation, and successful promotion.
- [ ] Run the tests and confirm promotion tests fail.
- [ ] Implement review-diff generation plus plan and execute using one-time approval records and atomic directory replacement.
- [ ] Run the full suite.

### Task 3: Rollback and Skill orchestration

**Files:**
- Modify: `scripts/evolution.py`
- Modify: `tests/test_darwin.py`
- Modify: `skills/darwin/SKILL.md`
- Modify: `skills/darwin/agents/openai.yaml`
- Modify: `README.md`
- Modify: `.codex-plugin/plugin.json`
- Modify: `ACCEPTANCE.md`

**Interfaces:**
- Produces: `rollback_plan(data_dir, candidate_id)` and `rollback_execute(data_dir, approval_id, approval_text)`
- Documents: observe, diagnose, candidate edit, real evaluation, approval, promotion, and rollback commands

- [ ] Write a failing test for separately approved rollback restoring the baseline hash.
- [ ] Implement rollback and verify the test passes.
- [ ] Update the Skill instructions to edit only the candidate path and to separate proposal prompts from validation prompts.
- [ ] Update version and acceptance documentation.
- [ ] Run unittest, plugin validation, Skill validation, JSON parsing, and CLI help checks.
- [ ] Commit the completed v0.2 implementation.
