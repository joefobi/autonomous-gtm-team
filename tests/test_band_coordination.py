from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any

from hospital_gtm.band import BandClient, BandCommandError, SharedTask
from hospital_gtm.coordination import (
    BandCoordinator,
    CoordinationError,
    HandoffPayload,
    StrategyProposal,
    validate_strategy_approval,
)
from hospital_gtm.models import DecisionRequest


def completed(
    stdout: str = "ok", returncode: int = 0
) -> subprocess.CompletedProcess[str]:
    """Build a subprocess result for adapter tests.

    Args:
        stdout: Standard output value.
        returncode: Process exit code.

    Returns:
        A configured subprocess result.
    """
    return subprocess.CompletedProcess(["band"], returncode, stdout, "")


class FakeRunner:
    """Capture Band commands and return configured JSON responses."""

    def __init__(self, responses: list[str]) -> None:
        """Initialize the fake runner.

        Args:
            responses: Standard output values returned in order.
        """
        self.responses = responses
        self.commands: list[list[str]] = []

    def __call__(
        self, command: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        """Return the next fake Band response.

        Args:
            command: Command passed to subprocess.
            kwargs: Subprocess options.

        Returns:
            A configured subprocess result.
        """
        del kwargs
        self.commands.append(command)
        return completed(self.responses.pop(0))


class BandClientTests(unittest.TestCase):
    def test_uses_documented_commands_and_parses_board(self) -> None:
        """Use Band plan, board, and message command shapes."""
        runner = FakeRunner(
            [
                "ok",
                json.dumps(
                    {
                        "tasks": [
                            {
                                "uid": "#1",
                                "subject": "Research",
                                "detail": "sources",
                                "status": "pending",
                                "owners": ["owner/researcher"],
                            }
                        ]
                    }
                ),
            ]
        )
        client = BandClient(cwd=Path("/tmp/project"), runner=runner)

        client.set_plan("room", Path("plan.md"), "owner/strategist")
        tasks = client.board("room", "owner/strategist")

        self.assertEqual(
            tasks,
            (
                SharedTask(
                    "#1", "Research", "sources", "pending", ("owner/researcher",)
                ),
            ),
        )
        self.assertEqual(runner.commands[0][:4], ["band", "plan", "set", "room"])
        self.assertIn("--snapshot", runner.commands[0])
        self.assertIn("--json", runner.commands[1])
        self.assertIn("--as", runner.commands[1])

    def test_rejects_failed_band_command(self) -> None:
        """Surface Band command failures instead of simulating success."""
        runner = FakeRunner([])

        def failing_runner(
            command: list[str], **kwargs: Any
        ) -> subprocess.CompletedProcess[str]:
            """Return a failed subprocess result.

            Args:
                command: Command passed to subprocess.
                kwargs: Subprocess options.

            Returns:
                A failed subprocess result.
            """
            del command, kwargs
            return subprocess.CompletedProcess(["band"], 1, "", "not authenticated")

        client = BandClient(runner=failing_runner)
        with self.assertRaises(BandCommandError):
            client.send_message("room", "@owner/researcher hello", "owner/strategist")
        del runner


class CoordinationTests(unittest.TestCase):
    def test_founder_request_contains_decision_fields(self) -> None:
        """Send options, recommendation, rationale, and pending action."""
        runner = FakeRunner(['{"answer": "approved"}'])
        coordinator = BandCoordinator(
            BandClient(runner=runner),
            "room",
            "owner/strategist",
            "owner/researcher",
        )
        proposal = StrategyProposal(
            hospital_id="hospital-a",
            strategy_version="strategy_v1",
            recommendation="Interview operations",
            rationale="Evidence supports discovery, not a product claim.",
            pending_action="Approve the discovery direction.",
            source_record_ids=("record_001",),
        )

        answer = coordinator.request_founder_decision(proposal, ("approved", "revise"))

        self.assertEqual(answer["answer"], "approved")
        prompt = runner.commands[0][3]
        self.assertIn("Recommendation: Interview operations", prompt)
        self.assertIn("Rationale: Evidence supports discovery", prompt)
        self.assertIn("Pending action: Approve", prompt)
        self.assertEqual(runner.commands[0].count("--option"), 2)

    def test_two_agent_vertical_slice_preserves_handoff_and_evidence(self) -> None:
        """Coordinate plan, assignment, handoff, and completion through Band."""
        board = json.dumps(
            {
                "tasks": [
                    {
                        "uid": "#1",
                        "subject": "Research hospital patient-flow priorities",
                        "detail": "scope",
                        "status": "pending",
                        "owners": [],
                    }
                ]
            }
        )
        runner = FakeRunner(["ok", "ok", board, "ok", "ok", "ok", "ok", "ok"])
        client = BandClient(runner=runner)
        coordinator = BandCoordinator(
            client, "room", "owner/strategist", "owner/researcher"
        )
        with tempfile.TemporaryDirectory() as directory:
            coordinator.publish_plan(Path(directory) / "plan.md")
        task = coordinator.assign_research_task("hospital-a")
        coordinator.start_research(task)
        handoff = HandoffPayload(
            hospital_id="hospital-a",
            task_id="#1",
            summary="Public source supports a discovery conversation.",
            record_ids=("record_001",),
            expected_next_action="Recall evidence and propose discovery questions.",
            open_questions=("Who owns inpatient readiness?",),
        )
        coordinator.complete_research(task, handoff)

        self.assertIn("@owner/strategist", runner.commands[5][3])
        self.assertIn("record_001", runner.commands[5][3])
        self.assertEqual(runner.commands[-1][1:4], ["work", "room-status", "room"])

    def test_stale_or_unapproved_strategy_cannot_handoff(self) -> None:
        """Require explicit approval for the current strategy version."""
        proposal = StrategyProposal(
            hospital_id="hospital-a",
            strategy_version="strategy_v2",
            recommendation="Interview operations",
            rationale="Public evidence supports discovery, not a product claim.",
            pending_action="Approve the discovery direction.",
            source_record_ids=("record_001",),
        )
        stale = DecisionRequest(
            hospital_id="hospital-a",
            strategy_version="strategy_v1",
            options=("approved", "revise"),
            recommendation="approved",
            explicit_answer="approved",
            rationale="Earlier version.",
            author_agent="founder",
            idempotency_key="decision:stale",
        )
        rejected = DecisionRequest(
            hospital_id="hospital-a",
            strategy_version="strategy_v2",
            options=("approved", "revise"),
            recommendation="approved",
            explicit_answer="revise",
            rationale="Need more evidence.",
            author_agent="founder",
            idempotency_key="decision:revise",
        )

        self.assertFalse(validate_strategy_approval(proposal, stale).approved)
        self.assertFalse(validate_strategy_approval(proposal, rejected).approved)
        self.assertEqual(
            validate_strategy_approval(proposal, stale).reason,
            "decision targets a stale strategy version",
        )

        coordinator = BandCoordinator(
            BandClient(runner=FakeRunner([])),
            "room",
            "owner/strategist",
            "owner/researcher",
        )
        with self.assertRaises(CoordinationError):
            coordinator.handoff_approved_strategy(proposal, stale, "owner/outreach")

    def test_handoff_requires_record_ids_and_matching_task(self) -> None:
        """Reject incomplete evidence handoffs."""
        with self.assertRaises(CoordinationError):
            HandoffPayload("hospital-a", "#1", "summary", (), "next", ())
