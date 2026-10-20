"""Hospital research, strategy, approval, outreach, and learning workflow."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol

from hospital_gtm.band import BandClient
from hospital_gtm.client import MemoryClient
from hospital_gtm.coordination import (
    ApprovalCheck,
    BandCoordinator,
    StrategyProposal,
    validate_strategy_approval,
)
from hospital_gtm.models import (
    DecisionRequest,
    EvidenceStatus,
    IndexingState,
    MemoryRecord,
    RecallResult,
    RecordKind,
    RememberResult,
)
from hospital_gtm.research_tools import (
    ResearchFinding,
    SourceDocument,
    extract_findings,
    load_source,
    stable_record_id,
)


class WorkflowError(RuntimeError):
    """Raised when a GTM workflow step cannot safely continue."""


class MemoryGateway(Protocol):
    """Memory operations required by the GTM workflow."""

    def remember(self, record: MemoryRecord) -> RememberResult:
        """Persist one memory record."""
        ...

    def recall(self, hospital_id: str, query: str, limit: int = 20) -> RecallResult:
        """Recall hospital-scoped records."""
        ...

    def get_record(self, record_id: str) -> MemoryRecord:
        """Retrieve one canonical record."""
        ...

    def record_decision(self, decision: DecisionRequest) -> object:
        """Persist one founder decision."""
        ...

    def list_records(
        self,
        hospital_id: str,
        kind: RecordKind | None = None,
    ) -> tuple[MemoryRecord, ...]:
        """List ready canonical records for a hospital."""
        ...


@dataclass(frozen=True, slots=True)
class ResearchResult:
    """Result of loading and storing supplied research sources."""

    hospital_id: str
    documents: tuple[SourceDocument, ...]
    findings: tuple[ResearchFinding, ...]
    records: tuple[MemoryRecord, ...]
    remember_results: tuple[RememberResult, ...]

    def record_ids(self) -> tuple[str, ...]:
        """Return canonical IDs written by the research run.

        Returns:
            Research record IDs.
        """
        return tuple(record.record_id for record in self.records)


@dataclass(frozen=True, slots=True)
class StrategyDocument:
    """Versioned opportunity strategy derived from recalled evidence."""

    hospital_id: str
    strategy_version: str
    recommendation: str
    rationale: str
    buyer_hypotheses: tuple[str, ...]
    unknowns: tuple[str, ...]
    discovery_questions: tuple[str, ...]
    pilot_scope: tuple[str, ...]
    data_needs: tuple[str, ...]
    success_measure: str
    source_record_ids: tuple[str, ...]
    feedback_record_ids: tuple[str, ...]

    def to_mapping(self) -> dict[str, object]:
        """Return JSON-compatible strategy fields.

        Returns:
            Serialized strategy document.
        """
        return {
            "hospital_id": self.hospital_id,
            "strategy_version": self.strategy_version,
            "recommendation": self.recommendation,
            "rationale": self.rationale,
            "buyer_hypotheses": list(self.buyer_hypotheses),
            "unknowns": list(self.unknowns),
            "discovery_questions": list(self.discovery_questions),
            "pilot_scope": list(self.pilot_scope),
            "data_needs": list(self.data_needs),
            "success_measure": self.success_measure,
            "source_record_ids": list(self.source_record_ids),
            "feedback_record_ids": list(self.feedback_record_ids),
        }

    def to_record(self, author_agent: str) -> MemoryRecord:
        """Convert the strategy to a canonical memory record.

        Args:
            author_agent: Agent writing the strategy.

        Returns:
            Versioned strategy memory record.
        """
        record_id = f"strategy_{self.hospital_id}_{self.strategy_version}"
        return MemoryRecord(
            record_id=record_id,
            hospital_id=self.hospital_id,
            kind=RecordKind.STRATEGY,
            content=json.dumps(self.to_mapping(), sort_keys=True),
            evidence_status=EvidenceStatus.UNVERIFIED,
            author_agent=author_agent,
            idempotency_key=f"strategy:{self.hospital_id}:{self.strategy_version}",
            source_record_ids=self.source_record_ids,
            strategy_version=self.strategy_version,
        )


@dataclass(frozen=True, slots=True)
class StrategyResult:
    """Stored strategy and its indexing response."""

    strategy: StrategyDocument
    record: MemoryRecord
    remember_result: RememberResult


@dataclass(frozen=True, slots=True)
class ApprovalResult:
    """Founder decision linked to one strategy version."""

    decision: DecisionRequest
    decision_id: str
    record_id: str
    check: ApprovalCheck


@dataclass(frozen=True, slots=True)
class OutreachDraft:
    """Approval-gated discovery outreach draft."""

    hospital_id: str
    strategy_version: str
    subject: str
    body: str
    source_record_ids: tuple[str, ...]
    status: str = "draft"

    def to_mapping(self) -> dict[str, object]:
        """Return JSON-compatible outreach fields.

        Returns:
            Serialized outreach draft.
        """
        return {
            "hospital_id": self.hospital_id,
            "strategy_version": self.strategy_version,
            "subject": self.subject,
            "body": self.body,
            "source_record_ids": list(self.source_record_ids),
            "status": self.status,
            "external_send": False,
        }

    def to_record(self, author_agent: str) -> MemoryRecord:
        """Convert the draft to a canonical memory record.

        Args:
            author_agent: Agent writing the draft.

        Returns:
            Outreach draft memory record.
        """
        record_id = f"outreach_{self.hospital_id}_{self.strategy_version}"
        return MemoryRecord(
            record_id=record_id,
            hospital_id=self.hospital_id,
            kind=RecordKind.OUTREACH_DRAFT,
            content=json.dumps(self.to_mapping(), sort_keys=True),
            evidence_status=EvidenceStatus.UNVERIFIED,
            author_agent=author_agent,
            idempotency_key=f"outreach:{self.hospital_id}:{self.strategy_version}",
            source_record_ids=self.source_record_ids,
            strategy_version=self.strategy_version,
        )


@dataclass(frozen=True, slots=True)
class LearningSummary:
    """Structured comparison between two strategy versions."""

    hospital_id: str
    prior_strategy_version: str
    revised_strategy_version: str
    prior_recommendation: str
    revised_recommendation: str
    feedback_record_ids: tuple[str, ...]
    retrieved_record_ids: tuple[str, ...]
    change_explanation: str

    def to_mapping(self) -> dict[str, object]:
        """Return JSON-compatible learning fields.

        Returns:
            Serialized learning summary.
        """
        return {
            "hospital_id": self.hospital_id,
            "prior_strategy_version": self.prior_strategy_version,
            "revised_strategy_version": self.revised_strategy_version,
            "prior_recommendation": self.prior_recommendation,
            "revised_recommendation": self.revised_recommendation,
            "feedback_record_ids": list(self.feedback_record_ids),
            "retrieved_record_ids": list(self.retrieved_record_ids),
            "change_explanation": self.change_explanation,
        }


@dataclass(frozen=True, slots=True)
class DemoResult:
    """Artifacts produced by the full PR3 workflow."""

    research: ResearchResult
    initial_strategy: StrategyResult
    approval: ApprovalResult
    outreach: OutreachDraft
    feedback: MemoryRecord
    revised_strategy: StrategyResult
    learning_summary: LearningSummary
    output_paths: Mapping[str, Path]


class HospitalGTMWorkflow:
    """Build a sourced hospital opportunity on shared memory."""

    def __init__(
        self,
        memory: MemoryGateway,
        output_dir: Path = Path("outputs"),
        band: BandCoordinator | None = None,
        author_agent: str = "strategist",
    ) -> None:
        """Initialize a workflow session.

        Args:
            memory: Shared memory service or client.
            output_dir: Directory for generated workflow artifacts.
            band: Optional Band coordinator used for founder decisions.
            author_agent: Strategist identity for generated records.
        """
        self.memory = memory
        self.output_dir = output_dir
        self.band = band
        self.author_agent = author_agent

    def research(
        self,
        hospital_id: str,
        sources: Sequence[str | Path],
        author_agent: str = "researcher",
    ) -> ResearchResult:
        """Load sources, extract findings, and persist ready records.

        Args:
            hospital_id: Hospital namespace for the research.
            sources: Local source files or public URLs.
            author_agent: Researcher identity writing findings.

        Returns:
            Stored research documents, findings, and results.
        """
        if not sources:
            raise WorkflowError("at least one research source is required")
        documents: list[SourceDocument] = []
        findings: list[ResearchFinding] = []
        records: list[MemoryRecord] = []
        remember_results: list[RememberResult] = []
        for source in sources:
            document = load_source(source)
            documents.append(document)
            source_findings = extract_findings(document, hospital_id)
            for finding in source_findings:
                record = finding.to_record(author_agent)
                result = self._remember_ready(record)
                findings.append(finding)
                records.append(record)
                remember_results.append(result)
        return ResearchResult(
            hospital_id=hospital_id,
            documents=tuple(documents),
            findings=tuple(findings),
            records=tuple(records),
            remember_results=tuple(remember_results),
        )

    def store_feedback(
        self,
        hospital_id: str,
        source: str | Path,
        author_agent: str = "founder",
        evidence_status: EvidenceStatus = EvidenceStatus.FOUNDER_CONFIRMED,
    ) -> MemoryRecord:
        """Store discovery feedback with its evidence status.

        Args:
            hospital_id: Hospital namespace for the feedback.
            source: Feedback source file or public URL.
            author_agent: Agent recording the feedback.
            evidence_status: Provenance status for the feedback.

        Returns:
            Stored discovery feedback record.
        """
        document = load_source(source)
        record_id = stable_record_id(hospital_id, document, "feedback")
        label = (
            "SIMULATED DISCOVERY FEEDBACK"
            if evidence_status is EvidenceStatus.SIMULATED
            else "DISCOVERY FEEDBACK"
        )
        record = MemoryRecord(
            record_id=record_id,
            hospital_id=hospital_id,
            kind=RecordKind.DISCOVERY_FEEDBACK,
            content=f"{label}: {document.text}",
            evidence_status=evidence_status,
            author_agent=author_agent,
            idempotency_key=f"feedback:{record_id}",
            source_url=document.source_url,
            source_file=document.source_file,
            source_title=document.title,
            observed_at=document.accessed_at,
        )
        self._remember_ready(record)
        return record

    def generate_strategy(
        self,
        hospital_id: str,
        strategy_version: str,
        research_record_ids: Sequence[str] = (),
    ) -> StrategyResult:
        """Recall evidence and persist a versioned strategy.

        Args:
            hospital_id: Hospital namespace for the strategy.
            strategy_version: New strategy version identifier.
            research_record_ids: Optional records to include explicitly.

        Returns:
            Stored strategy and indexing response.
        """
        records_by_id = {
            record.record_id: record
            for kind in (RecordKind.PUBLIC_EVIDENCE, RecordKind.DISCOVERY_FEEDBACK)
            for record in self._recall_records_by_kind(hospital_id, kind)
        }
        for record_id in research_record_ids:
            record = self.memory.get_record(record_id)
            if record.hospital_id != hospital_id:
                raise WorkflowError("strategy evidence belongs to another hospital")
            records_by_id[record.record_id] = record
        records = tuple(records_by_id.values())
        sourced = tuple(
            record for record in records if record.kind is RecordKind.PUBLIC_EVIDENCE
        )
        feedback = tuple(
            record for record in records if record.kind is RecordKind.DISCOVERY_FEEDBACK
        )
        if not sourced:
            raise WorkflowError("strategy requires at least one sourced public record")
        feedback_text = " ".join(record.content.lower() for record in feedback)
        shifted = "inpatient bed readiness" in feedback_text
        if shifted:
            recommendation = (
                "Prioritize discovery about inpatient bed readiness and discharge "
                "coordination before evaluating ED arrival forecasting."
            )
            rationale = (
                "Discovery feedback changed the priority toward inpatient "
                "readiness; public evidence still does not establish buyer intent, "
                "available data, or pilot value."
            )
        else:
            recommendation = (
                "Interview ED and inpatient operations leaders before selecting an "
                "arrival-forecasting or bed-readiness pilot."
            )
            rationale = (
                "Public evidence establishes the hospital and emergency care, but "
                "not the operational bottleneck, buyer, data availability, or "
                "willingness to run a pilot."
            )
        source_ids = tuple(record.record_id for record in sourced)
        feedback_ids = tuple(record.record_id for record in feedback)
        strategy = StrategyDocument(
            hospital_id=hospital_id,
            strategy_version=strategy_version,
            recommendation=recommendation,
            rationale=rationale,
            buyer_hypotheses=(
                "ED operations leadership may own arrival and treatment-space planning.",
                "Inpatient flow or bed-management leadership may own readiness and boarding.",
            ),
            unknowns=(
                "Actual patient-flow bottleneck",
                "Decision owner and buying process",
                "Available operational data and refresh cadence",
                "Customer-defined pilot success measure",
            ),
            discovery_questions=(
                "Where does patient flow become constrained during high demand?",
                "Who owns the decision and the operational response?",
                "Which arrival, staffing, bed, and discharge signals are available?",
                "What small pilot would be safe and useful to evaluate?",
            ),
            pilot_scope=(
                "One operational workflow and one customer-approved owner",
                "Historical or operational data assessment before any prediction claim",
                "A customer-agreed success measure rather than an invented target",
            ),
            data_needs=(
                "ED arrivals and timestamps",
                "Staffed capacity and inpatient bed readiness timestamps",
                "Discharge coordination signals",
            ),
            success_measure="A measure agreed with the customer after discovery.",
            source_record_ids=source_ids + feedback_ids,
            feedback_record_ids=feedback_ids,
        )
        record = strategy.to_record(self.author_agent)
        result = self._remember_ready(record)
        return StrategyResult(strategy, record, result)

    def approve_strategy(
        self,
        strategy: StrategyDocument,
        options: Sequence[str] = ("approved", "revise"),
    ) -> ApprovalResult:
        """Ask the founder through Band and persist the answer.

        Args:
            strategy: Strategy awaiting founder review.
            options: Selectable founder answers.

        Returns:
            Persisted decision and approval validation.
        """
        if self.band is None:
            raise WorkflowError("Band coordinator is required for founder approval")
        proposal = StrategyProposal(
            hospital_id=strategy.hospital_id,
            strategy_version=strategy.strategy_version,
            recommendation=strategy.recommendation,
            rationale=strategy.rationale,
            pending_action="Approve or revise the discovery direction before outreach.",
            source_record_ids=strategy.source_record_ids,
        )
        answer_payload = self.band.request_founder_decision(proposal, options)
        explicit_answer = _answer_from_band(answer_payload)
        decision = DecisionRequest(
            hospital_id=strategy.hospital_id,
            strategy_version=strategy.strategy_version,
            options=tuple(options),
            recommendation=strategy.recommendation,
            explicit_answer=explicit_answer,
            rationale=strategy.rationale,
            author_agent="founder",
            idempotency_key=f"decision:{strategy.hospital_id}:{strategy.strategy_version}",
            observed_at=date.today().isoformat(),
        )
        response = self.memory.record_decision(decision)
        record_id = _response_string(response, "record_id")
        decision_id = _response_string(response, "decision_id")
        indexing_state = _response_string(response, "indexing_state")
        if indexing_state != IndexingState.READY.value:
            raise WorkflowError("founder decision was not indexed and cannot gate work")
        check = validate_strategy_approval(proposal, decision)
        return ApprovalResult(decision, decision_id, record_id, check)

    def draft_outreach(
        self,
        strategy: StrategyDocument,
        approval: ApprovalResult,
    ) -> OutreachDraft:
        """Create and persist outreach after current approval.

        Args:
            strategy: Strategy to turn into a discovery draft.
            approval: Founder approval for that exact strategy version.

        Returns:
            Stored outreach draft.
        """
        proposal = StrategyProposal(
            hospital_id=strategy.hospital_id,
            strategy_version=strategy.strategy_version,
            recommendation=strategy.recommendation,
            rationale=strategy.rationale,
            pending_action="Approve or revise the discovery direction before outreach.",
            source_record_ids=strategy.source_record_ids,
        )
        check = validate_strategy_approval(proposal, approval.decision)
        if not check.approved:
            raise WorkflowError(check.reason)
        sourced_records = tuple(
            self.memory.get_record(record_id)
            for record_id in strategy.source_record_ids
            if self.memory.get_record(record_id).evidence_status
            is EvidenceStatus.SOURCED
        )
        if not sourced_records:
            raise WorkflowError("outreach requires a sourced evidence record")
        source = sourced_records[0]
        excerpt = source.content.split("Excerpt:", 1)[-1].strip()
        body = (
            f"Hello,\n\nI am exploring how hospital teams plan patient flow. "
            f"Public material for {source.source_title or strategy.hospital_id} "
            f"references: {excerpt}\n\n"
            "Would you be open to a short discovery conversation about where flow "
            "becomes constrained, which team owns the response, and what data or "
            "pilot measure would be useful? This is a discovery request, not a "
            "claim of clinical or throughput improvement.\n\nBest,\nFounder"
        )
        draft = OutreachDraft(
            hospital_id=strategy.hospital_id,
            strategy_version=strategy.strategy_version,
            subject="Exploring patient-flow planning",
            body=body,
            source_record_ids=tuple(record.record_id for record in sourced_records),
        )
        self._remember_ready(draft.to_record(self.author_agent))
        return draft

    def build_learning_summary(
        self,
        prior: StrategyDocument,
        revised: StrategyDocument,
    ) -> LearningSummary:
        """Explain how recalled feedback changed a strategy.

        Args:
            prior: Earlier strategy version.
            revised: Fresh-session strategy version.

        Returns:
            Structured learning summary.
        """
        if prior.hospital_id != revised.hospital_id:
            raise WorkflowError("learning strategies must use one hospital")
        if not revised.feedback_record_ids:
            raise WorkflowError("learning summary requires feedback records")
        if prior.recommendation == revised.recommendation:
            change_explanation = (
                "Fresh-session recall retrieved feedback, but the "
                "recommendation did not change: "
                f"{revised.recommendation}"
            )
        else:
            change_explanation = (
                "Fresh-session recall retrieved feedback and changed "
                "the recommendation from "
                f"{prior.recommendation} to {revised.recommendation}"
            )
        return LearningSummary(
            hospital_id=prior.hospital_id,
            prior_strategy_version=prior.strategy_version,
            revised_strategy_version=revised.strategy_version,
            prior_recommendation=prior.recommendation,
            revised_recommendation=revised.recommendation,
            feedback_record_ids=revised.feedback_record_ids,
            retrieved_record_ids=revised.source_record_ids,
            change_explanation=change_explanation,
        )

    def write_outputs(
        self,
        strategy: StrategyDocument,
        outreach: OutreachDraft,
        learning: LearningSummary,
    ) -> dict[str, Path]:
        """Write structured opportunity, outreach, and learning outputs.

        Args:
            strategy: Final strategy to publish in the brief.
            outreach: Approved outreach draft.
            learning: Strategy-change summary.

        Returns:
            Output names mapped to written paths.
        """
        target = self.output_dir / strategy.hospital_id
        target.mkdir(parents=True, exist_ok=True)
        records = tuple(
            self.memory.get_record(record_id)
            for record_id in strategy.source_record_ids
        )
        brief = _render_brief(strategy, records)
        paths = {
            "opportunity_brief_md": target / "opportunity_brief.md",
            "opportunity_brief_json": target / "opportunity_brief.json",
            "outreach_draft_md": target / "outreach_draft.md",
            "outreach_draft_json": target / "outreach_draft.json",
            "learning_summary_md": target / "learning_summary.md",
            "learning_summary_json": target / "learning_summary.json",
        }
        paths["opportunity_brief_md"].write_text(brief, encoding="utf-8")
        paths["opportunity_brief_json"].write_text(
            json.dumps(
                {
                    **strategy.to_mapping(),
                    "sources": [_source_mapping(record) for record in records],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        paths["outreach_draft_md"].write_text(
            f"# {outreach.subject}\n\nStatus: `{outreach.status}`\n\n{outreach.body}\n",
            encoding="utf-8",
        )
        paths["outreach_draft_json"].write_text(
            json.dumps(outreach.to_mapping(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        learning_markdown = _render_learning(learning)
        paths["learning_summary_md"].write_text(learning_markdown, encoding="utf-8")
        paths["learning_summary_json"].write_text(
            json.dumps(learning.to_mapping(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return paths

    def run_demo(
        self,
        hospital_id: str,
        sources: Sequence[str | Path],
        feedback_source: str | Path,
        feedback_status: EvidenceStatus = EvidenceStatus.FOUNDER_CONFIRMED,
    ) -> DemoResult:
        """Run research, approval, outreach, feedback, and fresh recall.

        Args:
            hospital_id: Hospital namespace for the demo.
            sources: Supplied public research sources.
            feedback_source: Discovery feedback source file or public URL.
            feedback_status: Provenance status for the feedback source.

        Returns:
            Full workflow result and output paths.
        """
        research_result = self.research(hospital_id, sources)
        initial_version, revised_version = self._next_demo_versions(hospital_id)
        initial = self.generate_strategy(
            hospital_id, initial_version, research_result.record_ids()
        )
        approval = self.approve_strategy(initial.strategy)
        if not approval.check.approved:
            raise WorkflowError("demo requires explicit founder approval")
        outreach = self.draft_outreach(initial.strategy, approval)
        feedback = self.store_feedback(
            hospital_id, feedback_source, evidence_status=feedback_status
        )
        fresh_session = HospitalGTMWorkflow(
            self.memory,
            self.output_dir,
            self.band,
            self.author_agent,
        )
        revised = fresh_session.generate_strategy(hospital_id, revised_version)
        learning = fresh_session.build_learning_summary(
            initial.strategy, revised.strategy
        )
        paths = fresh_session.write_outputs(revised.strategy, outreach, learning)
        return DemoResult(
            research_result,
            initial,
            approval,
            outreach,
            feedback,
            revised,
            learning,
            paths,
        )

    def _next_demo_versions(self, hospital_id: str) -> tuple[str, str]:
        """Allocate two strategy versions that do not reuse prior runs.

        Args:
            hospital_id: Hospital namespace for the demo.

        Returns:
            Initial and revised strategy version identifiers.
        """
        recalled = self.memory.list_records(hospital_id, RecordKind.STRATEGY)
        versions: list[int] = []
        for record in recalled:
            if record.kind is not RecordKind.STRATEGY or not record.strategy_version:
                continue
            prefix = "strategy_v"
            if record.strategy_version.startswith(prefix):
                suffix = record.strategy_version[len(prefix) :]
                if suffix.isdigit():
                    versions.append(int(suffix))
        next_version = max(versions, default=0) + 1
        return f"strategy_v{next_version}", f"strategy_v{next_version + 1}"

    def _recall_records_by_kind(
        self,
        hospital_id: str,
        kind: RecordKind,
    ) -> tuple[MemoryRecord, ...]:
        """Recall relevant records and complete the set from canonical storage.

        Args:
            hospital_id: Hospital namespace for the records.
            kind: Record kind to retrieve.

        Returns:
            All ready records of the requested kind.
        """
        canonical = self.memory.list_records(hospital_id, kind)
        recalled = self.memory.recall(
            hospital_id,
            f"kind {kind.value} hospital patient flow emergency bed discharge",
            limit=100,
        )
        ordered: list[MemoryRecord] = []
        seen: set[str] = set()
        for match in recalled.matches:
            if match.record.kind is kind:
                ordered.append(match.record)
                seen.add(match.record.record_id)
        ordered.extend(record for record in canonical if record.record_id not in seen)
        return tuple(ordered)

    def _remember_ready(self, record: MemoryRecord) -> RememberResult:
        """Persist a record and require ready indexing.

        Args:
            record: Record to persist.

        Returns:
            Ready memory result.
        """
        result = self.memory.remember(record)
        if result.indexing_state is not IndexingState.READY:
            raise WorkflowError(
                f"memory record {record.record_id} is not ready: {result.error or 'unknown error'}"
            )
        return result


def _answer_from_band(payload: Mapping[str, object]) -> str:
    """Extract a founder answer from Band's response payload.

    Args:
        payload: Decoded Band answer.

    Returns:
        Explicit founder answer.
    """
    for field_name in ("explicit_answer", "answer"):
        value = payload.get(field_name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    selected = payload.get("selected_options")
    if isinstance(selected, list) and selected and isinstance(selected[0], str):
        return selected[0].strip()
    raise WorkflowError("Band founder response has no explicit answer")


def _response_string(response: object, field_name: str) -> str:
    """Read a required field from a memory response.

    Args:
        response: Memory service response object.
        field_name: Required response field.

    Returns:
        Response field value.
    """
    value: object
    if isinstance(response, Mapping):
        value = response.get(field_name)
    else:
        value = getattr(response, field_name, None)
    if isinstance(value, IndexingState):
        return value.value
    if not isinstance(value, str) or not value.strip():
        raise WorkflowError(f"memory response has no {field_name}")
    return value


def _source_mapping(record: MemoryRecord) -> dict[str, object]:
    """Return concise source provenance for output files.

    Args:
        record: Canonical source record.

    Returns:
        Source provenance fields.
    """
    return {
        "record_id": record.record_id,
        "evidence_status": record.evidence_status.value,
        "source_url": record.source_url,
        "source_file": record.source_file,
        "source_title": record.source_title,
        "observed_at": record.observed_at,
        "excerpt": record.content.split("Excerpt:", 1)[-1].strip(),
    }


def _render_brief(
    strategy: StrategyDocument,
    records: Sequence[MemoryRecord],
) -> str:
    """Render a sourced opportunity brief.

    Args:
        strategy: Strategy document to render.
        records: Supporting canonical records.

    Returns:
        Markdown opportunity brief.
    """
    lines = [
        f"# Opportunity brief: {strategy.hospital_id}",
        "",
        f"Strategy version: `{strategy.strategy_version}`",
        "",
        "## Recommendation",
        "",
        strategy.recommendation,
        "",
        "## Rationale",
        "",
        strategy.rationale,
        "",
        "## Buyer hypotheses",
        "",
        *[f"- {item}" for item in strategy.buyer_hypotheses],
        "",
        "## Unknowns",
        "",
        *[f"- {item}" for item in strategy.unknowns],
        "",
        "## Discovery questions",
        "",
        *[f"- {item}" for item in strategy.discovery_questions],
        "",
        "## Proposed pilot",
        "",
        *[f"- {item}" for item in strategy.pilot_scope],
        "",
        f"Success measure: {strategy.success_measure}",
        "",
        "## Source references",
        "",
    ]
    for record in records:
        source = record.source_url or record.source_file or "unknown source"
        simulated = (
            " (simulated)" if record.evidence_status is EvidenceStatus.SIMULATED else ""
        )
        lines.append(
            f"- `{record.record_id}`{simulated}: {record.source_title or source} "
            f"({source}, accessed {record.observed_at or 'unknown date'})"
        )
    return "\n".join(lines) + "\n"


def _render_learning(summary: LearningSummary) -> str:
    """Render a strategy learning summary.

    Args:
        summary: Learning summary to render.

    Returns:
        Markdown learning summary.
    """
    return (
        f"# Learning summary: {summary.hospital_id}\n\n"
        f"Prior strategy: `{summary.prior_strategy_version}`\n\n"
        f"Prior recommendation: {summary.prior_recommendation}\n\n"
        f"Revised strategy: `{summary.revised_strategy_version}`\n\n"
        f"Revised recommendation: {summary.revised_recommendation}\n\n"
        f"{summary.change_explanation}\n\n"
        "Retrieved records:\n"
        + "\n".join(f"- `{record_id}`" for record_id in summary.retrieved_record_ids)
        + "\n\nFeedback records:\n"
        + "\n".join(f"- `{record_id}`" for record_id in summary.feedback_record_ids)
        + "\n"
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the PR3 workflow against a configured Band room.

    Args:
        argv: Optional command-line arguments.

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(prog="gtm-demo")
    parser.add_argument("--hospital-id", required=True)
    parser.add_argument("--source", action="append", required=True)
    parser.add_argument("--feedback", required=True)
    parser.add_argument(
        "--feedback-status",
        choices=tuple(status.value for status in EvidenceStatus),
        default=EvidenceStatus.FOUNDER_CONFIRMED.value,
        help="Evidence status for the feedback source.",
    )
    parser.add_argument("--db", default="data/memory.sqlite3")
    parser.add_argument(
        "--memory-url",
        help="Use an already-running memory service instead of local in-process memory.",
    )
    parser.add_argument("--outputs", default="outputs")
    parser.add_argument("--room-id", required=True)
    parser.add_argument("--strategist", required=True)
    parser.add_argument("--researcher", required=True)
    args = parser.parse_args(argv)
    from hospital_gtm.service import MemoryService
    from hospital_gtm.store import SQLiteRecordStore

    memory: MemoryGateway
    if args.memory_url:
        memory = MemoryClient(args.memory_url)
    else:
        memory = MemoryService(SQLiteRecordStore(args.db))
    band = BandCoordinator(
        BandClient(cwd=Path.cwd()),
        args.room_id,
        args.strategist,
        args.researcher,
    )
    result = HospitalGTMWorkflow(memory, Path(args.outputs), band).run_demo(
        args.hospital_id,
        args.source,
        args.feedback,
        EvidenceStatus(args.feedback_status),
    )
    print(
        json.dumps(
            {name: str(path) for name, path in result.output_paths.items()},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
