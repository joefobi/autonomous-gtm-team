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
