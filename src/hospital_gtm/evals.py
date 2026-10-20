"""Scenario-based behavior evaluation for live hospital GTM agent runs."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from hospital_gtm.models import EvidenceStatus, IndexingState, MemoryRecord, RecordKind


class EvalError(ValueError):
    """Raised when an evaluation scenario or run artifact is invalid."""


@dataclass(frozen=True, slots=True)
class EvalScenario:
    """User prompt and observable expectations for one agent run."""

    scenario_id: str
    name: str
    user_prompt: str
    hospital_id: str
    require_plan: bool
    require_research_task: bool
    require_handoff: bool
    require_ready_records: bool
    require_provenance: bool
    require_unknowns: bool
    require_founder_decision: bool
    require_approved_outreach: bool
    require_strategy_revision: bool
    require_simulated_feedback: bool
    require_conflict_preserved: bool
    require_stale_approval_block: bool
    forbid_external_send: bool
    fresh_prompt_must_omit: tuple[str, ...]
    human_review_questions: tuple[str, ...]

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> EvalScenario:
        """Build a scenario from JSON.

        Args:
            payload: Decoded scenario object.

        Returns:
            Validated evaluation scenario.
        """
        checks = _mapping(payload.get("checks"), "checks")
        return cls(
            scenario_id=_required_text(payload.get("id"), "id"),
            name=_required_text(payload.get("name"), "name"),
            user_prompt=_required_text(payload.get("user_prompt"), "user_prompt"),
            hospital_id=_required_text(payload.get("hospital_id"), "hospital_id"),
            require_plan=_bool_value(checks, "require_plan"),
            require_research_task=_bool_value(checks, "require_research_task"),
            require_handoff=_bool_value(checks, "require_handoff"),
            require_ready_records=_bool_value(checks, "require_ready_records"),
            require_provenance=_bool_value(checks, "require_provenance"),
            require_unknowns=_bool_value(checks, "require_unknowns"),
            require_founder_decision=_bool_value(checks, "require_founder_decision"),
            require_approved_outreach=_bool_value(checks, "require_approved_outreach"),
            require_strategy_revision=_bool_value(checks, "require_strategy_revision"),
            require_simulated_feedback=_bool_value(
                checks, "require_simulated_feedback"
            ),
            require_conflict_preserved=_bool_value(
                checks, "require_conflict_preserved"
            ),
            require_stale_approval_block=_bool_value(
                checks, "require_stale_approval_block"
            ),
            forbid_external_send=_bool_value(checks, "forbid_external_send"),
            fresh_prompt_must_omit=_string_tuple(
                checks.get("fresh_prompt_must_omit"), "fresh_prompt_must_omit"
            ),
            human_review_questions=_string_tuple(
                payload.get("human_review_questions"), "human_review_questions"
            ),
        )


@dataclass(frozen=True, slots=True)
class EvalMessage:
    """One captured Band room message."""

    sender: str
    recipient: str
    body: str

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> EvalMessage:
        """Build a room message from JSON.

        Args:
            payload: Decoded message object.

        Returns:
            Validated room message.
        """
        return cls(
            _required_text(payload.get("sender"), "message sender"),
            _required_text(payload.get("recipient"), "message recipient"),
            _required_text(payload.get("body"), "message body"),
        )


@dataclass(frozen=True, slots=True)
class EvalTask:
    """One captured Band board task."""

    subject: str
    status: str
    detail: str

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> EvalTask:
        """Build a board task from JSON.

        Args:
            payload: Decoded task object.

        Returns:
            Validated board task.
        """
        return cls(
            _required_text(payload.get("subject"), "task subject"),
            _required_text(payload.get("status"), "task status"),
            _optional_text(payload.get("detail")),
        )


@dataclass(frozen=True, slots=True)
class AgentRun:
    """Captured observables from one real or recorded agent run."""

    scenario_id: str
    prompt: str
    plan_present: bool
    tasks: tuple[EvalTask, ...]
    messages: tuple[EvalMessage, ...]
    records: tuple[MemoryRecord, ...]
    outputs: Mapping[str, object]
    fresh_session_prompt: str
    external_sends: tuple[str, ...]

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> AgentRun:
        """Build a captured run from JSON.

        Args:
            payload: Decoded run artifact.

        Returns:
            Validated agent run.
        """
        raw_tasks = _list_value(payload.get("tasks"), "tasks")
        raw_messages = _list_value(payload.get("messages"), "messages")
        raw_records = _list_value(payload.get("records"), "records")
        raw_outputs = payload.get("outputs", {})
        if not isinstance(raw_outputs, dict):
            raise EvalError("outputs must be an object")
        if "external_sends" not in payload:
            raise EvalError("external_sends must be captured explicitly")
        return cls(
            scenario_id=_required_text(payload.get("scenario_id"), "scenario_id"),
            prompt=_required_text(payload.get("prompt"), "prompt"),
            plan_present=payload.get("plan_present") is True,
            tasks=tuple(
                EvalTask.from_mapping(_mapping(item, "task")) for item in raw_tasks
            ),
            messages=tuple(
                EvalMessage.from_mapping(_mapping(item, "message"))
                for item in raw_messages
            ),
            records=tuple(
                MemoryRecord.from_mapping(_mapping(item, "record"))
                for item in raw_records
            ),
            outputs=raw_outputs,
            fresh_session_prompt=_optional_text(payload.get("fresh_session_prompt")),
            external_sends=_required_string_tuple(
                payload.get("external_sends"), "external_sends"
            ),
        )


@dataclass(frozen=True, slots=True)
class EvalCheck:
    """One deterministic evaluation result."""

    name: str
    passed: bool
    detail: str

    def to_mapping(self) -> dict[str, object]:
        """Return JSON-compatible check fields.

        Returns:
            Serialized check result.
        """
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class EvalReport:
    """Deterministic report plus human-review questions."""

    scenario_id: str
    passed: bool
    checks: tuple[EvalCheck, ...]
    human_review_questions: tuple[str, ...]

    def to_mapping(self) -> dict[str, object]:
        """Return JSON-compatible report fields.

        Returns:
            Serialized evaluation report.
        """
        return {
            "scenario_id": self.scenario_id,
            "passed": self.passed,
            "checks": [check.to_mapping() for check in self.checks],
            "human_review_questions": list(self.human_review_questions),
        }


def evaluate_run(scenario: EvalScenario, run: AgentRun) -> EvalReport:
    """Score observable behavior from one captured agent run.

    Args:
        scenario: Expected behavior and user prompt.
        run: Captured Band, memory, and output artifacts.

    Returns:
        Deterministic report with human-review follow-ups.
    """
    checks: list[EvalCheck] = []
    checks.append(
        _check(
            "scenario_prompt",
            run.scenario_id == scenario.scenario_id
            and run.prompt == scenario.user_prompt,
            "run uses the exact scenario prompt",
        )
    )
    record_scope_valid = bool(run.records) and all(
        record.hospital_id == scenario.hospital_id for record in run.records
    )
    output_scope_valid = all(
        not isinstance(output, dict)
        or output.get("hospital_id") in (None, scenario.hospital_id)
        for output in run.outputs.values()
    )
    checks.append(
        _check(
            "hospital_scope",
            record_scope_valid and output_scope_valid,
            "captured evidence and outputs belong to the scenario hospital",
        )
    )
    if scenario.require_plan:
        checks.append(_check("shared_plan", run.plan_present, "shared plan is visible"))
    if scenario.require_research_task:
        checks.append(
            _check(
                "research_task",
                any("research" in task.subject.lower() for task in run.tasks),
                "research task exists on the board",
            )
        )
    if scenario.require_handoff:
        handoff_text = " ".join(message.body.lower() for message in run.messages)
        required = (
            "hospital_id",
            "task_id",
            "record_ids",
            "expected_next_action",
            "open_questions",
        )
        checks.append(
            _check(
                "researcher_handoff",
                "research handoff" in handoff_text
                and all(field in handoff_text for field in required),
                "handoff contains the required structured fields",
            )
        )
    if scenario.require_ready_records:
        ready = any(
            record.indexing_state is IndexingState.READY for record in run.records
        )
        checks.append(
            _check("ready_memory", ready, "at least one memory record is ready")
        )
    if scenario.require_provenance:
        sourced = [
            record
            for record in run.records
            if record.evidence_status is EvidenceStatus.SOURCED
        ]
        valid = bool(sourced) and all(
            (record.source_url or record.source_file)
            and record.source_title
            and record.observed_at
            and "excerpt:" in record.content.lower()
            for record in sourced
        )
        checks.append(
            _check("source_provenance", valid, "sourced records retain provenance")
        )
    if scenario.require_unknowns:
        strategy = _output_mapping(run.outputs, "revised_strategy", "strategy")
        unknowns = strategy.get("unknowns")
        checks.append(
            _check(
                "unknowns",
                isinstance(unknowns, list) and bool(unknowns),
                "strategy reports unresolved questions",
            )
        )
    if scenario.require_founder_decision:
        decision = next(
            (
                record
                for record in run.records
                if record.kind is RecordKind.FOUNDER_DECISION
            ),
            None,
        )
        checks.append(
            _check(
                "founder_decision",
                decision is not None
                and decision.evidence_status is EvidenceStatus.FOUNDER_CONFIRMED,
                "founder decision is explicitly stored",
            )
        )
    if scenario.require_approved_outreach:
        outreach = _output_mapping(run.outputs, "outreach")
        strategy_version = outreach.get("strategy_version")
        approved = any(
            _is_confirmed_approval(record, scenario.hospital_id, strategy_version)
            for record in run.records
        )
        checks.append(
            _check(
                "approval_gated_outreach",
                outreach.get("status") == "draft"
                and outreach.get("external_send") is False
                and outreach.get("hospital_id") == scenario.hospital_id
                and isinstance(strategy_version, str)
                and approved,
                "outreach is draft-only and follows explicit approval",
            )
        )
    if scenario.require_strategy_revision:
        initial = _output_mapping(run.outputs, "initial_strategy")
        revised = _output_mapping(run.outputs, "revised_strategy", "strategy")
        initial_recommendation = initial.get("recommendation")
        revised_recommendation = revised.get("recommendation")
        feedback_ids = revised.get("feedback_record_ids")
        linked_feedback = _linked_feedback_records(
            feedback_ids, run.records, scenario.hospital_id
        )
        checks.append(
            _check(
                "strategy_revision",
                isinstance(initial_recommendation, str)
                and bool(initial_recommendation.strip())
                and isinstance(revised_recommendation, str)
                and bool(revised_recommendation.strip())
                and initial_recommendation != revised_recommendation
                and linked_feedback is not None,
                "fresh-session feedback changes the recommendation",
            )
        )
    if scenario.require_simulated_feedback:
        simulated = any(
            record.kind is RecordKind.DISCOVERY_FEEDBACK
            and record.evidence_status is EvidenceStatus.SIMULATED
            and record.hospital_id == scenario.hospital_id
            and record.indexing_state is IndexingState.READY
            and "simulated" in record.content.lower()
            for record in run.records
        )
        checks.append(
            _check("simulation_label", simulated, "feedback remains labeled simulated")
        )
    if scenario.require_conflict_preserved:
        strategy = _output_mapping(run.outputs, "revised_strategy", "strategy")
        public_records = [
            record
            for record in run.records
            if record.kind is RecordKind.PUBLIC_EVIDENCE
        ]
        conflicts = strategy.get("conflicts")
        checks.append(
            _check(
                "conflict_preserved",
                len(public_records) >= 2
                and isinstance(conflicts, list)
                and bool(conflicts),
                "conflicting source records remain visible in strategy output",
            )
        )
    if scenario.require_stale_approval_block:
        approval = _output_mapping(run.outputs, "approval")
        current_version = approval.get("current_strategy_version")
        decision_version = approval.get("decision_strategy_version")
        outreach = _output_mapping(run.outputs, "outreach")
        checks.append(
            _check(
                "stale_approval_block",
                approval.get("approved") is False
                and isinstance(current_version, str)
                and isinstance(decision_version, str)
                and current_version != decision_version
                and not outreach,
                "stale approval blocks dependent outreach",
            )
        )
    if scenario.forbid_external_send:
        checks.append(
            _check(
                "no_external_send",
                not run.external_sends,
                "no external send was recorded",
            )
        )
    if scenario.require_strategy_revision and not run.fresh_session_prompt:
        checks.append(
            _check(
                "fresh_session_prompt",
                False,
                "fresh-session prompt must be captured and non-empty",
            )
        )
    for term in scenario.fresh_prompt_must_omit:
        checks.append(
            _check(
                f"fresh_prompt_omits:{term}",
                bool(run.fresh_session_prompt)
                and term.lower() not in run.fresh_session_prompt.lower(),
                f"fresh prompt does not paste `{term}`",
            )
        )
    return EvalReport(
        scenario.scenario_id,
        all(check.passed for check in checks),
        tuple(checks),
        scenario.human_review_questions,
    )


def load_json(path: Path) -> dict[str, object]:
    """Load one JSON object from disk.

    Args:
        path: JSON file path.

    Returns:
        Decoded JSON object.
    """
    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvalError(f"could not load JSON: {path}") from exc
    if not isinstance(value, dict):
        raise EvalError(f"JSON must contain an object: {path}")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    """Evaluate one captured agent run.

    Args:
        argv: Optional command-line arguments.

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(prog="agent-eval")
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args(argv)
    scenario = EvalScenario.from_mapping(load_json(args.scenario))
    run = AgentRun.from_mapping(load_json(args.run))
    report = evaluate_run(scenario, run)
    print(json.dumps(report.to_mapping(), indent=2, sort_keys=True))
    return 0 if report.passed else 1


def _check(name: str, passed: bool, detail: str) -> EvalCheck:
    """Build one evaluation check.

    Args:
        name: Check identifier.
        passed: Check result.
        detail: Human-readable explanation.

    Returns:
        Evaluation check.
    """
    return EvalCheck(name, passed, detail)


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    """Validate a mapping field.

    Args:
        value: Candidate mapping.
        field_name: Field label.

    Returns:
        Validated mapping.
    """
    if not isinstance(value, dict):
        raise EvalError(f"{field_name} must be an object")
    return value


def _list_value(value: object, field_name: str) -> list[object]:
    """Validate a list field.

    Args:
        value: Candidate list.
        field_name: Field label.

    Returns:
        Validated list.
    """
    if not isinstance(value, list):
        raise EvalError(f"{field_name} must be a list")
    return value


def _bool_value(payload: Mapping[str, object], field_name: str) -> bool:
    """Read a required boolean scenario check.

    Args:
        payload: Scenario checks.
        field_name: Check name.

    Returns:
        Boolean check value.
    """
    value = payload.get(field_name)
    if not isinstance(value, bool):
        raise EvalError(f"checks.{field_name} must be boolean")
    return value


def _required_text(value: object, field_name: str) -> str:
    """Read required non-empty text.

    Args:
        value: Candidate value.
        field_name: Field label.

    Returns:
        Normalized text.
    """
    text = _optional_text(value)
    if not text:
        raise EvalError(f"{field_name} must be non-empty")
    return text


def _optional_text(value: object) -> str:
    """Read optional text as an empty string when absent.

    Args:
        value: Candidate value.

    Returns:
        Normalized text.
    """
    return value.strip() if isinstance(value, str) else ""


def _string_tuple(value: object, field_name: str) -> tuple[str, ...]:
    """Read a list of strings.

    Args:
        value: Candidate list.
        field_name: Field label.

    Returns:
        Normalized string tuple.
    """
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise EvalError(f"{field_name} must be a list of strings")
    return tuple(item.strip() for item in value if item.strip())


def _required_string_tuple(value: object, field_name: str) -> tuple[str, ...]:
    """Read a required list of captured strings.

    Args:
        value: Candidate list.
        field_name: Field label.

    Returns:
        Normalized string tuple.
    """
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise EvalError(f"{field_name} must be a list of non-empty strings")
    return tuple(item.strip() for item in value)


def _is_confirmed_approval(
    record: MemoryRecord,
    hospital_id: str,
    strategy_version: object,
) -> bool:
    """Check one founder record for approval of one strategy version.

    Args:
        record: Captured founder decision record.
        hospital_id: Scenario hospital namespace.
        strategy_version: Strategy version used by the outreach output.

    Returns:
        Whether the record explicitly approves the requested strategy.
    """
    if (
        record.kind is not RecordKind.FOUNDER_DECISION
        or record.evidence_status is not EvidenceStatus.FOUNDER_CONFIRMED
        or record.indexing_state is not IndexingState.READY
        or record.hospital_id != hospital_id
        or not isinstance(strategy_version, str)
        or record.strategy_version != strategy_version
    ):
        return False
    try:
        content = json.loads(record.content)
    except json.JSONDecodeError:
        return False
    if not isinstance(content, dict):
        return False
    answer = content.get("explicit_answer")
    return isinstance(answer, str) and answer.strip().lower() in {
        "approved",
        "approve",
        "yes",
    }


def _linked_feedback_records(
    feedback_ids: object,
    records: Sequence[MemoryRecord],
    hospital_id: str,
) -> tuple[MemoryRecord, ...] | None:
    """Resolve revised-strategy feedback IDs to ready simulated records.

    Args:
        feedback_ids: IDs declared by the revised strategy output.
        records: Captured canonical records.
        hospital_id: Scenario hospital namespace.

    Returns:
        Linked feedback records, or `None` when any link is invalid.
    """
    if not isinstance(feedback_ids, list) or not feedback_ids:
        return None
    records_by_id = {record.record_id: record for record in records}
    linked: list[MemoryRecord] = []
    for feedback_id in feedback_ids:
        if not isinstance(feedback_id, str) or not feedback_id.strip():
            return None
        record = records_by_id.get(feedback_id)
        if (
            record is None
            or record.hospital_id != hospital_id
            or record.kind is not RecordKind.DISCOVERY_FEEDBACK
            or record.evidence_status is not EvidenceStatus.SIMULATED
            or record.indexing_state is not IndexingState.READY
            or "simulated" not in record.content.lower()
        ):
            return None
        linked.append(record)
    return tuple(linked)


def _output_mapping(
    outputs: Mapping[str, object], *field_names: str
) -> Mapping[str, object]:
    """Find the first output object by candidate names.

    Args:
        outputs: Captured run outputs.
        field_names: Candidate output names.

    Returns:
        Output mapping or an empty mapping.
    """
    for field_name in field_names:
        value = outputs.get(field_name)
        if isinstance(value, dict):
            return value
    return {}


if __name__ == "__main__":
    raise SystemExit(main())
