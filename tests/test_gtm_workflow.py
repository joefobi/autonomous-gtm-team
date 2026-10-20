from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any

from hospital_gtm.band import BandClient
from hospital_gtm.coordination import BandCoordinator
from hospital_gtm.models import (
    EvidenceStatus,
    IndexingState,
    MemoryRecord,
    RecordKind,
)
from hospital_gtm.service import MemoryService
from hospital_gtm.store import SQLiteRecordStore
from hospital_gtm.workflow import HospitalGTMWorkflow

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "fixtures/johns_hopkins_hospital/public_evidence.json"
FEEDBACK = ROOT / "fixtures/johns_hopkins_hospital/discovery_feedback.json"


class ApprovalRunner:
    """Return a founder approval for the Band question."""

    def __init__(self) -> None:
        """Initialize the command capture."""
        self.commands: list[list[str]] = []

    def __call__(
        self, command: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        """Return an approved Band response.

        Args:
            command: Command passed to subprocess.
            kwargs: Subprocess options.

        Returns:
            Approved founder response.
        """
        del kwargs
        self.commands.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            json.dumps({"answer": "approved"}),
            "",
        )


class GTMWorkflowTests(unittest.TestCase):
    def test_full_demo_revises_strategy_from_fresh_memory_session(self) -> None:
        """Run research, approval, outreach, feedback, recall, and outputs."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            memory = MemoryService(SQLiteRecordStore(root / "memory.sqlite3"))
            runner = ApprovalRunner()
            band = BandCoordinator(
                BandClient(runner=runner),
                "room-001",
                "owner/strategist",
                "owner/researcher",
            )
            workflow = HospitalGTMWorkflow(memory, root / "outputs", band)

            result = workflow.run_demo(
                "johns_hopkins_hospital",
                (SOURCE,),
                FEEDBACK,
            )

            self.assertEqual(result.approval.check.approved, True)
            self.assertEqual(result.approval.decision.strategy_version, "strategy_v1")
            self.assertEqual(
                result.revised_strategy.strategy.strategy_version, "strategy_v2"
            )
            self.assertNotEqual(
                result.initial_strategy.strategy.recommendation,
                result.revised_strategy.strategy.recommendation,
            )
            self.assertIn(
                "inpatient bed readiness",
                result.revised_strategy.strategy.recommendation,
            )
            self.assertEqual(result.outreach.status, "draft")
            self.assertNotIn("send", " ".join(runner.commands[0]))
            self.assertEqual(result.feedback.evidence_status, EvidenceStatus.SIMULATED)
            self.assertEqual(
                result.revised_strategy.remember_result.indexing_state,
                IndexingState.READY,
            )
            self.assertTrue(result.output_paths["opportunity_brief_md"].is_file())
            self.assertTrue(result.output_paths["outreach_draft_json"].is_file())
            self.assertTrue(result.output_paths["learning_summary_md"].is_file())

            fresh_memory = MemoryService(SQLiteRecordStore(root / "memory.sqlite3"))
            recalled = fresh_memory.recall(
                "johns_hopkins_hospital", "inpatient bed readiness"
            )
            feedback_records = [
                match.record
                for match in recalled.matches
                if match.record.kind is RecordKind.DISCOVERY_FEEDBACK
            ]
            self.assertEqual(len(feedback_records), 1)
            self.assertEqual(
                feedback_records[0].evidence_status, EvidenceStatus.SIMULATED
            )

    def test_demo_allocates_new_versions_on_repeat_run(self) -> None:
        """Allow a persisted demo database to run again without idempotency errors."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            memory = MemoryService(SQLiteRecordStore(root / "memory.sqlite3"))
            runner = ApprovalRunner()
            band = BandCoordinator(
                BandClient(runner=runner),
                "room-001",
                "owner/strategist",
                "owner/researcher",
            )
            workflow = HospitalGTMWorkflow(memory, root / "outputs", band)

            first = workflow.run_demo(
                "johns_hopkins_hospital",
                (SOURCE,),
                FEEDBACK,
            )
            second = workflow.run_demo(
                "johns_hopkins_hospital",
                (SOURCE,),
                FEEDBACK,
            )

            self.assertEqual(
                first.initial_strategy.strategy.strategy_version, "strategy_v1"
            )
            self.assertEqual(
                second.initial_strategy.strategy.strategy_version, "strategy_v3"
            )
        self.assertEqual(
            second.revised_strategy.strategy.strategy_version, "strategy_v4"
        )
        self.assertIn(
            "recommendation did not change",
            second.learning_summary.change_explanation,
        )

    def test_negative_feedback_does_not_prioritize_inpatient_readiness(self) -> None:
        """Interpret an explicit negative feedback decision in the right direction."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            feedback_path = root / "feedback.json"
            feedback_path.write_text(
                json.dumps(
                    {
                        "source_title": "Simulated negative feedback",
                        "source_file": str(feedback_path),
                        "observed_at": "2026-10-20",
                        "content": "Do not prioritize inpatient bed readiness; focus on ED arrivals.",
                    }
                ),
                encoding="utf-8",
            )
            workflow = HospitalGTMWorkflow(
                MemoryService(SQLiteRecordStore(root / "memory.sqlite3"))
            )
            workflow.research("johns_hopkins_hospital", (SOURCE,))
            workflow.store_feedback("johns_hopkins_hospital", feedback_path)

            result = workflow.generate_strategy("johns_hopkins_hospital", "strategy_v1")

            self.assertTrue(
                result.strategy.recommendation.startswith(
                    "Prioritize discovery about ED arrival demand"
                )
            )

    def test_unverified_public_evidence_cannot_support_strategy(self) -> None:
        """Do not treat unverified public records as sourced evidence."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            memory = MemoryService(SQLiteRecordStore(root / "memory.sqlite3"))
            unverified = MemoryRecord(
                record_id="unverified_public",
                hospital_id="johns_hopkins_hospital",
                kind=RecordKind.PUBLIC_EVIDENCE,
                content="Claim: emergency patient flow. Excerpt: supplied context.",
                evidence_status=EvidenceStatus.UNVERIFIED,
                author_agent="test",
                idempotency_key="test:unverified_public",
                source_file="tests/fixture.md",
                source_title="Test source",
                indexing_state=IndexingState.READY,
            )
            result = memory.remember(unverified)
            self.assertEqual(result.indexing_state, IndexingState.READY)

            with self.assertRaisesRegex(RuntimeError, "sourced public record"):
                HospitalGTMWorkflow(memory).generate_strategy(
                    "johns_hopkins_hospital", "strategy_v1"
                )

    def test_research_requires_sources_and_preserves_provenance(self) -> None:
        """Require a source and retain its URL, file, title, and excerpt."""
        with tempfile.TemporaryDirectory() as directory:
            memory = MemoryService(
                SQLiteRecordStore(Path(directory) / "memory.sqlite3")
            )
            workflow = HospitalGTMWorkflow(memory)
            with self.assertRaisesRegex(RuntimeError, "at least one"):
                workflow.research("johns_hopkins_hospital", ())

            result = workflow.research("johns_hopkins_hospital", (SOURCE,))
            record = result.records[0]
            self.assertEqual(record.evidence_status, EvidenceStatus.SOURCED)
            self.assertIn("Excerpt:", record.content)
            self.assertEqual(
                record.source_url,
                "https://www.hopkinsmedicine.org/patient-care/locations/the-johns-hopkins-hospital",
            )
            self.assertEqual(record.source_file, str(SOURCE))
            self.assertEqual(
                record.source_title,
                "The Johns Hopkins Hospital | Johns Hopkins Medicine",
            )
