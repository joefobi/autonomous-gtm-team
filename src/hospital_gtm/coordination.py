"""Band coordination contracts for the hospital GTM workflow."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from hospital_gtm.band import BandClient, BandCommandResult, SharedTask
from hospital_gtm.models import DecisionRequest


class CoordinationError(ValueError):
    """Raised when a Band workflow contract is invalid."""


@dataclass(frozen=True, slots=True)
class HandoffPayload:
    """Evidence payload passed between Band agents."""

    hospital_id: str
    task_id: str
    summary: str
    record_ids: tuple[str, ...]
    expected_next_action: str
    open_questions: tuple[str, ...]

    def __post_init__(self) -> None:
        """Validate handoff fields."""
        for field_name in (
            "hospital_id",
            "task_id",
            "summary",
            "expected_next_action",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise CoordinationError(f"{field_name} must be non-empty")
        if not self.record_ids:
            raise CoordinationError("record_ids must contain at least one record")
        if any(not record_id.strip() for record_id in self.record_ids):
            raise CoordinationError("record_ids must contain non-empty values")

    def to_mapping(self) -> dict[str, object]:
        """Return a JSON-compatible handoff payload.

        Returns:
            Serialized handoff fields.
        """
        return {
            "hospital_id": self.hospital_id,
            "task_id": self.task_id,
            "summary": self.summary,
            "record_ids": list(self.record_ids),
            "expected_next_action": self.expected_next_action,
            "open_questions": list(self.open_questions),
        }

    def to_message(self, recipient_handle: str) -> str:
        """Render an explicit Band recipient handoff.

        Args:
            recipient_handle: Band handle that must receive the handoff.

        Returns:
            Message body with serialized handoff fields.
        """
        if not recipient_handle.strip():
            raise CoordinationError("recipient_handle must be non-empty")
        payload = json.dumps(self.to_mapping(), sort_keys=True)
        return f"@{recipient_handle.strip()} Research handoff: {payload}"


@dataclass(frozen=True, slots=True)
class StrategyProposal:
    """Versioned strategy awaiting a founder decision."""

    hospital_id: str
    strategy_version: str
    recommendation: str
    rationale: str
    pending_action: str
    source_record_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        """Validate strategy identity and evidence links."""
        for field_name in (
            "hospital_id",
            "strategy_version",
            "recommendation",
            "rationale",
            "pending_action",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise CoordinationError(f"{field_name} must be non-empty")
        if not self.source_record_ids:
            raise CoordinationError("source_record_ids must contain evidence")


@dataclass(frozen=True, slots=True)
class ApprovalCheck:
    """Result of validating a founder decision against a strategy."""

    approved: bool
    reason: str


def validate_strategy_approval(
    proposal: StrategyProposal, decision: DecisionRequest
) -> ApprovalCheck:
    """Validate a founder decision for the current strategy.

    Args:
        proposal: Current strategy proposal.
        decision: Explicit founder decision.

    Returns:
        Approval result and an actionable reason.
    """
    if decision.hospital_id != proposal.hospital_id:
        return ApprovalCheck(False, "decision hospital does not match strategy")
    if decision.strategy_version != proposal.strategy_version:
        return ApprovalCheck(False, "decision targets a stale strategy version")
    answer = decision.explicit_answer.strip().lower()
    if answer not in {"approved", "approve", "yes"}:
        return ApprovalCheck(False, "founder approval is required before handoff")
    return ApprovalCheck(True, "strategy is explicitly approved")


class BandCoordinator:
    """Coordinate the PR2 two-agent workflow through Band."""

    def __init__(
        self,
        band: BandClient,
        room_id: str,
        strategist_handle: str,
        researcher_handle: str,
    ) -> None:
        """Initialize a coordinator for one hospital room.

        Args:
            band: Band CLI adapter.
            room_id: Shared Band room identifier.
            strategist_handle: Strategist Band handle.
            researcher_handle: Researcher Band handle.
        """
        self.band = band
        self.room_id = room_id
        self.strategist_handle = strategist_handle
        self.researcher_handle = researcher_handle

    def publish_plan(self, source: Path) -> BandCommandResult:
        """Publish the strategist-owned room plan.

        Args:
            source: Markdown plan path.

        Returns:
            The Band command result.
        """
        return self.band.set_plan(
            self.room_id, source, self.strategist_handle, snapshot=True
        )

    def add_researcher(self) -> BandCommandResult:
        """Add the researcher to the shared room.

        Returns:
            The Band command result.
        """
        return self.band.add_participant(
            self.room_id, self.researcher_handle, self.strategist_handle
        )

    def assign_research_task(
        self,
        hospital_id: str,
        subject: str = "Research hospital patient-flow priorities",
    ) -> SharedTask:
        """Assign and locate the researcher task on the shared board.

        Args:
            hospital_id: Hospital namespace for the evaluation.
            subject: Shared task headline.

        Returns:
            The newly assigned shared task.
        """
        detail = (
            f"Hospital: {hospital_id}. Read supplied public sources, write sourced "
            "memory, and hand off record IDs and unknowns. Complete only after the "
            "memory write succeeds."
        )
        self.band.assign_task(
            self.room_id,
            subject,
            detail,
            self.strategist_handle,
            components=("research", "memory_service", "band_handoff"),
        )
        tasks = self.band.board(self.room_id, self.strategist_handle)
        matches = tuple(task for task in tasks if task.subject == subject)
        if not matches:
            raise CoordinationError("assigned task was not returned by Band board")
        return matches[-1]

    def start_research(
        self, task: SharedTask
    ) -> tuple[BandCommandResult, BandCommandResult]:
        """Give the researcher and start its shared task.

        Args:
            task: Task assigned to the researcher.

        Returns:
            Results for task assignment and status update.
        """
        taken = self.band.take_task(self.room_id, task.uid, self.researcher_handle)
        started = self.band.set_task_status(
            self.room_id, task.uid, "in_progress", self.researcher_handle
        )
        return taken, started

    def complete_research(
        self, task: SharedTask, handoff: HandoffPayload
    ) -> tuple[BandCommandResult, BandCommandResult]:
        """Publish evidence and complete a researcher handoff.

        Args:
            task: Research task being completed.
            handoff: Evidence payload for the strategist.

        Returns:
            Results for the handoff message and task completion.
        """
        if handoff.task_id != task.uid:
            raise CoordinationError("handoff task_id does not match shared task")
        message = self.band.send_message(
            self.room_id,
            handoff.to_message(self.strategist_handle),
            self.researcher_handle,
        )
        evidence = (
            f"Completed with memory record IDs: {', '.join(handoff.record_ids)}. "
            f"Open questions: {', '.join(handoff.open_questions) or 'none'}."
        )
        edited = self.band.edit_task(
            self.room_id, task.uid, evidence, self.researcher_handle
        )
        completed = self.band.set_task_status(
            self.room_id, task.uid, "completed", self.researcher_handle
        )
        del edited
        return message, completed

    def request_founder_decision(
        self,
        proposal: StrategyProposal,
        options: Sequence[str],
    ) -> dict[str, object]:
        """Ask the founder to approve a versioned strategy.

        Args:
            proposal: Strategy awaiting a decision.
            options: Decision options shown in Band.

        Returns:
            Structured Band answer payload.
        """
        prompt = (
            f"Hospital {proposal.hospital_id}: approve strategy "
            f"{proposal.strategy_version}?\n"
            f"Recommendation: {proposal.recommendation}\n"
            f"Rationale: {proposal.rationale}\n"
            f"Pending action: {proposal.pending_action}"
        )
        return self.band.ask_founder(prompt, options, self.strategist_handle)

    def handoff_approved_strategy(
        self,
        proposal: StrategyProposal,
        decision: DecisionRequest,
        outreach_handle: str,
    ) -> BandCommandResult:
        """Hand off a strategy only after current-version approval.

        Args:
            proposal: Current strategy proposal.
            decision: Founder decision to validate.
            outreach_handle: Band handle receiving the handoff.

        Returns:
            The Band command result.
        """
        check = validate_strategy_approval(proposal, decision)
        if not check.approved:
            raise CoordinationError(check.reason)
        message = json.dumps(
            {
                "hospital_id": proposal.hospital_id,
                "strategy_version": proposal.strategy_version,
                "recommendation": proposal.recommendation,
                "rationale": proposal.rationale,
                "pending_action": proposal.pending_action,
                "source_record_ids": list(proposal.source_record_ids),
                "approval": decision.explicit_answer,
            },
            sort_keys=True,
        )
        return self.band.send_message(
            self.room_id,
            f"@{outreach_handle} Approved strategy handoff: {message}",
            self.strategist_handle,
        )


def find_task(tasks: Sequence[SharedTask], subject: str) -> SharedTask | None:
    """Find the newest task with a matching subject.

    Args:
        tasks: Tasks returned by Band.
        subject: Exact task subject.

    Returns:
        The newest matching task or `None`.
    """
    matches = [task for task in tasks if task.subject == subject]
    return matches[-1] if matches else None
