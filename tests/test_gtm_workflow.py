from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any

from hospital_gtm.band import BandClient
from hospital_gtm.coordination import BandCoordinator
from hospital_gtm.models import EvidenceStatus, IndexingState, RecordKind
from hospital_gtm.research_tools import SourceDocument, stable_record_id
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

    def test_repeated_demo_allocates_new_strategy_versions(self) -> None:
        """Allow the same persistent database to run the demo twice."""
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

            first = workflow.run_demo("johns_hopkins_hospital", (SOURCE,), FEEDBACK)
            second = workflow.run_demo("johns_hopkins_hospital", (SOURCE,), FEEDBACK)

            self.assertEqual(
                first.initial_strategy.strategy.strategy_version, "strategy_v1"
            )
            self.assertEqual(
                first.revised_strategy.strategy.strategy_version, "strategy_v2"
            )
            self.assertEqual(
                second.initial_strategy.strategy.strategy_version, "strategy_v3"
            )
            self.assertEqual(
                second.revised_strategy.strategy.strategy_version, "strategy_v4"
            )

    def test_feedback_is_recalled_even_with_many_public_records(self) -> None:
        """Recall feedback separately instead of losing it to a result limit."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            memory = MemoryService(SQLiteRecordStore(root / "memory.sqlite3"))
            workflow = HospitalGTMWorkflow(memory)
            sources = []
            for index in range(25):
                source = root / f"source_{index}.txt"
                source.write_text(
                    "Public hospital evidence describes emergency patient flow.",
                    encoding="utf-8",
                )
                sources.append(source)

            workflow.research("johns_hopkins_hospital", tuple(sources))
            feedback = workflow.store_feedback("johns_hopkins_hospital", FEEDBACK)
            strategy = workflow.generate_strategy(
                "johns_hopkins_hospital", "strategy_v1"
            )

            self.assertIn(feedback.record_id, strategy.strategy.feedback_record_ids)

    def test_learning_summary_reports_when_feedback_does_not_change_strategy(
        self,
    ) -> None:
        """Report unchanged recommendations without claiming a false shift."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            memory = MemoryService(SQLiteRecordStore(root / "memory.sqlite3"))
            workflow = HospitalGTMWorkflow(memory)
            research = workflow.research("johns_hopkins_hospital", (SOURCE,))
            prior = workflow.generate_strategy(
                "johns_hopkins_hospital", "strategy_v1", research.record_ids()
            )
            feedback = root / "staffing_feedback.txt"
            feedback.write_text(
                "SIMULATED CUSTOMER FEEDBACK: focus on staffing schedules.",
                encoding="utf-8",
            )
            workflow.store_feedback("johns_hopkins_hospital", feedback)
            revised = workflow.generate_strategy(
                "johns_hopkins_hospital", "strategy_v2"
            )

            summary = workflow.build_learning_summary(prior.strategy, revised.strategy)

            self.assertEqual(
                prior.strategy.recommendation, revised.strategy.recommendation
            )
            self.assertIn("did not change", summary.change_explanation)

    def test_source_refresh_has_a_new_record_identity(self) -> None:
        """Allow a later observation of the same source to be stored."""
        first = SourceDocument(
            title="Hospital source",
            text="Current public evidence.",
            accessed_at="2026-10-20",
            source_url="https://example.com/hospital",
        )
        second = SourceDocument(
            title="Hospital source",
            text="Current public evidence.",
            accessed_at="2026-10-21",
            source_url="https://example.com/hospital",
        )

        self.assertNotEqual(
            stable_record_id("johns_hopkins_hospital", first, "research"),
            stable_record_id("johns_hopkins_hospital", second, "research"),
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
