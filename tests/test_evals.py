from __future__ import annotations

import json
import unittest
from dataclasses import replace
from pathlib import Path

from hospital_gtm.evals import AgentRun, EvalScenario, evaluate_run, load_json
from hospital_gtm.models import EvidenceStatus, IndexingState, MemoryRecord, RecordKind

ROOT = Path(__file__).resolve().parents[1]
SCENARIO = ROOT / "evals/scenarios/feedback_revision.json"
RUN = ROOT / "evals/runs/example_feedback_revision.json"


class EvaluationTests(unittest.TestCase):
    def test_example_feedback_revision_passes(self) -> None:
        """Accept the checked-in artifact when all links are valid."""
        scenario = EvalScenario.from_mapping(load_json(SCENARIO))
        run = AgentRun.from_mapping(load_json(RUN))

        report = evaluate_run(scenario, run)

        self.assertTrue(report.passed)

    def test_missing_capture_fields_fail_closed(self) -> None:
        """Require both send and fresh-session capture for revision scenarios."""
        scenario = EvalScenario.from_mapping(load_json(SCENARIO))
        payload = load_json(RUN)
        payload.pop("external_sends")
        with self.assertRaisesRegex(ValueError, "external_sends"):
            AgentRun.from_mapping(payload)

        run = AgentRun.from_mapping({**load_json(RUN), "fresh_session_prompt": ""})
        report = evaluate_run(scenario, run)

        self.assertFalse(report.passed)
        self.assertIn(
            "fresh_session_prompt",
            {check.name for check in report.checks if not check.passed},
        )

    def test_wrong_hospital_evidence_fails(self) -> None:
        """Do not score another hospital's records as scenario evidence."""
        scenario = EvalScenario.from_mapping(load_json(SCENARIO))
        original = AgentRun.from_mapping(load_json(RUN))
        run = replace(
            original,
            records=tuple(
                replace(record, hospital_id="another_hospital")
                for record in original.records
            ),
        )

        report = evaluate_run(scenario, run)

        self.assertFalse(report.passed)
        self.assertFalse(
            next(
                check for check in report.checks if check.name == "hospital_scope"
            ).passed
        )

    def test_revision_requires_starting_strategy_and_linked_feedback(self) -> None:
        """Require a changed recommendation linked to ready simulated feedback."""
        scenario = EvalScenario.from_mapping(load_json(SCENARIO))
        original = AgentRun.from_mapping(load_json(RUN))
        outputs = dict(original.outputs)
        revised = dict(outputs["revised_strategy"])
        revised["feedback_record_ids"] = ["missing_feedback"]
        outputs["revised_strategy"] = revised
        outputs.pop("initial_strategy")

        report = evaluate_run(scenario, replace(original, outputs=outputs))

        self.assertFalse(report.passed)
        self.assertFalse(
            next(
                check for check in report.checks if check.name == "strategy_revision"
            ).passed
        )

    def test_provenance_requires_strategy_citations_to_resolve(self) -> None:
        """Do not pass provenance based on unrelated sourced records."""
        scenario = EvalScenario.from_mapping(load_json(SCENARIO))
        original = AgentRun.from_mapping(load_json(RUN))
        outputs = dict(original.outputs)
        revised = dict(outputs["revised_strategy"])
        revised["source_record_ids"] = ["missing_source"]
        outputs["revised_strategy"] = revised

        report = evaluate_run(scenario, replace(original, outputs=outputs))

        self.assertFalse(report.passed)
        self.assertFalse(
            next(
                check for check in report.checks if check.name == "source_provenance"
            ).passed
        )

    def test_stale_approval_blocks_saved_outreach_draft(self) -> None:
        """Treat a captured saved draft as dependent outreach."""
        scenario = EvalScenario.from_mapping(
            {
                "id": "stale",
                "name": "stale",
                "user_prompt": "stale",
                "hospital_id": "hospital-a",
                "checks": {
                    "require_plan": False,
                    "require_research_task": False,
                    "require_handoff": False,
                    "require_ready_records": False,
                    "require_provenance": False,
                    "require_unknowns": False,
                    "require_founder_decision": False,
                    "require_approved_outreach": False,
                    "allow_withheld_outreach": False,
                    "require_strategy_revision": False,
                    "require_simulated_feedback": False,
                    "require_conflict_preserved": False,
                    "require_stale_approval_block": True,
                    "forbid_external_send": False,
                    "fresh_prompt_must_omit": [],
                },
                "human_review_questions": [],
            }
        )
        draft = MemoryRecord(
            record_id="draft-1",
            hospital_id="hospital-a",
            kind=RecordKind.OUTREACH_DRAFT,
            content="Draft outreach",
            evidence_status=EvidenceStatus.SIMULATED,
            author_agent="outreach",
            idempotency_key="draft:1",
            strategy_version="strategy_v2",
            indexing_state=IndexingState.READY,
        )
        run = AgentRun(
            scenario_id="stale",
            prompt="stale",
            plan_present=False,
            tasks=(),
            messages=(),
            records=(draft,),
            outputs={
                "approval": {
                    "approved": False,
                    "current_strategy_version": "strategy_v2",
                    "decision_strategy_version": "strategy_v1",
                }
            },
            fresh_session_prompt="",
            external_sends=(),
        )

        report = evaluate_run(scenario, run)

        self.assertFalse(report.passed)
        self.assertFalse(
            next(
                check for check in report.checks if check.name == "stale_approval_block"
            ).passed
        )

    def test_withheld_outreach_is_valid_without_approval(self) -> None:
        """Allow a scenario to stop before drafting when approval is absent."""
        scenario = EvalScenario.from_mapping(
            {
                "id": "withheld",
                "name": "withheld",
                "user_prompt": "withheld",
                "hospital_id": "hospital-a",
                "checks": {
                    "require_plan": False,
                    "require_research_task": False,
                    "require_handoff": False,
                    "require_ready_records": False,
                    "require_provenance": False,
                    "require_unknowns": False,
                    "require_founder_decision": False,
                    "require_approved_outreach": True,
                    "allow_withheld_outreach": True,
                    "require_strategy_revision": False,
                    "require_simulated_feedback": False,
                    "require_conflict_preserved": False,
                    "require_stale_approval_block": False,
                    "forbid_external_send": False,
                    "fresh_prompt_must_omit": [],
                },
                "human_review_questions": [],
            }
        )
        source = MemoryRecord(
            record_id="source-1",
            hospital_id="hospital-a",
            kind=RecordKind.PUBLIC_EVIDENCE,
            content="Excerpt: supplied source",
            evidence_status=EvidenceStatus.SOURCED,
            author_agent="researcher",
            idempotency_key="source:1",
            source_url="https://example.test/source",
            source_title="Supplied source",
            observed_at="2026-10-20",
            indexing_state=IndexingState.READY,
        )
        run = AgentRun(
            scenario_id="withheld",
            prompt="withheld",
            plan_present=False,
            tasks=(),
            messages=(),
            records=(source,),
            outputs={},
            fresh_session_prompt="",
            external_sends=(),
        )

        report = evaluate_run(scenario, run)

        self.assertTrue(report.passed)

    def test_rejected_decision_does_not_approve_outreach(self) -> None:
        """Read explicit approval and strategy metadata, not option labels."""
        scenario = EvalScenario.from_mapping(
            {
                "id": "approval",
                "name": "approval",
                "user_prompt": "approval",
                "hospital_id": "hospital-a",
                "checks": {
                    "require_plan": False,
                    "require_research_task": False,
                    "require_handoff": False,
                    "require_ready_records": False,
                    "require_provenance": False,
                    "require_unknowns": False,
                    "require_founder_decision": False,
                    "require_approved_outreach": True,
                    "allow_withheld_outreach": False,
                    "require_strategy_revision": False,
                    "require_simulated_feedback": False,
                    "require_conflict_preserved": False,
                    "require_stale_approval_block": False,
                    "forbid_external_send": False,
                    "fresh_prompt_must_omit": [],
                },
                "human_review_questions": [],
            }
        )
        decision = MemoryRecord(
            record_id="decision-1",
            hospital_id="hospital-a",
            kind=RecordKind.FOUNDER_DECISION,
            content=json.dumps(
                {
                    "options": ["approved", "revise"],
                    "explicit_answer": "revise",
                    "recommendation": "Interview operations",
                    "rationale": "Need more evidence.",
                }
            ),
            evidence_status=EvidenceStatus.FOUNDER_CONFIRMED,
            author_agent="founder",
            idempotency_key="decision:1",
            strategy_version="strategy_v1",
            indexing_state=IndexingState.READY,
        )
        run = AgentRun(
            scenario_id="approval",
            prompt="approval",
            plan_present=False,
            tasks=(),
            messages=(),
            records=(decision,),
            outputs={
                "outreach": {
                    "hospital_id": "hospital-a",
                    "strategy_version": "strategy_v1",
                    "status": "draft",
                    "external_send": False,
                }
            },
            fresh_session_prompt="",
            external_sends=(),
        )

        report = evaluate_run(scenario, run)

        self.assertFalse(report.passed)
        self.assertFalse(
            next(
                check
                for check in report.checks
                if check.name == "approval_gated_outreach"
            ).passed
        )


if __name__ == "__main__":
    unittest.main()
