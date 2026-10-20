"""Validated models for shared hospital memory."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Mapping, TypeVar

EnumType = TypeVar("EnumType", bound=StrEnum)


class ModelValidationError(ValueError):
    """Raised when an incoming memory payload is invalid."""


class RecordKind(StrEnum):
    """Kinds of records that can be retained in shared memory."""

    PUBLIC_EVIDENCE = "public_evidence"
    HYPOTHESIS = "hypothesis"
    DISCOVERY_FEEDBACK = "discovery_feedback"
    FOUNDER_DECISION = "founder_decision"
    STRATEGY = "strategy"
    OUTREACH_DRAFT = "outreach_draft"


class EvidenceStatus(StrEnum):
    """Provenance status attached to a memory record."""

    SOURCED = "sourced"
    UNVERIFIED = "unverified"
    SIMULATED = "simulated"
    FOUNDER_CONFIRMED = "founder_confirmed"


class IndexingState(StrEnum):
    """State of a record in the semantic or keyword index."""

    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ModelValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


def _optional_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ModelValidationError(f"{field_name} must be a string or null")
    value = value.strip()
    return value or None


def _enum_value(enum_type: type[EnumType], value: object, field_name: str) -> EnumType:
    text = _required_text(value, field_name)
    try:
        return enum_type(text)
    except ValueError as exc:
        choices = ", ".join(member.value for member in enum_type)
        raise ModelValidationError(f"{field_name} must be one of: {choices}") from exc


def _string_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ModelValidationError(f"{field_name} must be a list of strings")
    values: list[str] = []
    for item in value:
        values.append(_required_text(item, field_name))
    return tuple(values)


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    """Canonical record retained by the shared memory service."""

    record_id: str
    hospital_id: str
    kind: RecordKind
    content: str
    evidence_status: EvidenceStatus
    author_agent: str
    idempotency_key: str
    source_url: str | None = None
    source_file: str | None = None
    source_title: str | None = None
    observed_at: str | None = None
    created_at: str = ""
    source_record_ids: tuple[str, ...] = ()
    strategy_version: str | None = None
    supersedes_record_id: str | None = None
    indexing_state: IndexingState = IndexingState.PENDING
    indexing_error: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "record_id", _required_text(self.record_id, "record_id")
        )
        object.__setattr__(
            self, "hospital_id", _required_text(self.hospital_id, "hospital_id")
        )
        object.__setattr__(self, "content", _required_text(self.content, "content"))
        object.__setattr__(
            self, "author_agent", _required_text(self.author_agent, "author_agent")
        )
        object.__setattr__(
            self,
            "idempotency_key",
            _required_text(self.idempotency_key, "idempotency_key"),
        )
        object.__setattr__(
            self,
            "kind",
            _enum_value(RecordKind, self.kind, "kind"),
        )
        object.__setattr__(
            self,
            "evidence_status",
            _enum_value(EvidenceStatus, self.evidence_status, "evidence_status"),
        )
        object.__setattr__(
            self,
            "indexing_state",
            _enum_value(IndexingState, self.indexing_state, "indexing_state"),
        )
        for field_name in (
            "source_url",
            "source_file",
            "source_title",
            "observed_at",
            "strategy_version",
            "supersedes_record_id",
            "indexing_error",
        ):
            object.__setattr__(
                self,
                field_name,
                _optional_text(getattr(self, field_name), field_name),
            )
        object.__setattr__(
            self,
            "created_at",
            _required_text(self.created_at or _now(), "created_at"),
        )
        object.__setattr__(
            self,
            "source_record_ids",
            _string_tuple(self.source_record_ids, "source_record_ids"),
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> MemoryRecord:
        """Build and validate a record from decoded JSON."""

        return cls(
            record_id=payload.get("record_id"),  # type: ignore[arg-type]
            hospital_id=payload.get("hospital_id"),  # type: ignore[arg-type]
            kind=payload.get("kind"),  # type: ignore[arg-type]
            content=payload.get("content"),  # type: ignore[arg-type]
            evidence_status=payload.get("evidence_status"),  # type: ignore[arg-type]
            author_agent=payload.get("author_agent"),  # type: ignore[arg-type]
            idempotency_key=payload.get("idempotency_key"),  # type: ignore[arg-type]
            source_url=_optional_text(payload.get("source_url"), "source_url"),
            source_file=_optional_text(payload.get("source_file"), "source_file"),
            source_title=_optional_text(payload.get("source_title"), "source_title"),
            observed_at=_optional_text(payload.get("observed_at"), "observed_at"),
            created_at=_optional_text(payload.get("created_at"), "created_at") or "",
            source_record_ids=_string_tuple(
                payload.get("source_record_ids"), "source_record_ids"
            ),
            strategy_version=_optional_text(
                payload.get("strategy_version"), "strategy_version"
            ),
            supersedes_record_id=_optional_text(
                payload.get("supersedes_record_id"), "supersedes_record_id"
            ),
            indexing_state=_enum_value(
                IndexingState,
                payload.get("indexing_state", IndexingState.PENDING),
                "indexing_state",
            ),
            indexing_error=_optional_text(
                payload.get("indexing_error"), "indexing_error"
            ),
        )

    def payload_mapping(self) -> dict[str, object]:
        """Return fields that define record identity for idempotency checks."""

        payload = self.to_mapping()
        payload.pop("indexing_state", None)
        payload.pop("indexing_error", None)
        payload.pop("created_at", None)
        return payload

    def to_mapping(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""

        return {
            "record_id": self.record_id,
            "hospital_id": self.hospital_id,
            "kind": self.kind.value,
            "content": self.content,
            "evidence_status": self.evidence_status.value,
            "author_agent": self.author_agent,
            "idempotency_key": self.idempotency_key,
            "source_url": self.source_url,
            "source_file": self.source_file,
            "source_title": self.source_title,
            "observed_at": self.observed_at,
            "created_at": self.created_at,
            "source_record_ids": list(self.source_record_ids),
            "strategy_version": self.strategy_version,
            "supersedes_record_id": self.supersedes_record_id,
            "indexing_state": self.indexing_state.value,
            "indexing_error": self.indexing_error,
        }

    def index_text(self) -> str:
        """Return provenance-rich text for a semantic index."""

        fields = [
            f"record_id: {self.record_id}",
            f"hospital_id: {self.hospital_id}",
            f"kind: {self.kind.value}",
            f"evidence_status: {self.evidence_status.value}",
            f"source_title: {self.source_title or ''}",
            f"source_url: {self.source_url or ''}",
            f"source_file: {self.source_file or ''}",
            f"content: {self.content}",
        ]
        return "\n".join(fields)


@dataclass(frozen=True, slots=True)
class DecisionRequest:
    """Explicit founder decision linked to a strategy version."""

    hospital_id: str
    strategy_version: str
    options: tuple[str, ...]
    recommendation: str
    explicit_answer: str
    rationale: str
    author_agent: str
    idempotency_key: str
    observed_at: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "hospital_id",
            "strategy_version",
            "recommendation",
            "explicit_answer",
            "rationale",
            "author_agent",
            "idempotency_key",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name),
            )
        object.__setattr__(self, "options", _string_tuple(self.options, "options"))
        if not self.options:
            raise ModelValidationError("options must contain at least one option")
        object.__setattr__(
            self,
            "observed_at",
            _optional_text(self.observed_at, "observed_at"),
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> DecisionRequest:
        return cls(
            hospital_id=payload.get("hospital_id"),  # type: ignore[arg-type]
            strategy_version=payload.get("strategy_version"),  # type: ignore[arg-type]
            options=_string_tuple(payload.get("options"), "options"),
            recommendation=payload.get("recommendation"),  # type: ignore[arg-type]
            explicit_answer=payload.get("explicit_answer"),  # type: ignore[arg-type]
            rationale=payload.get("rationale"),  # type: ignore[arg-type]
            author_agent=payload.get("author_agent"),  # type: ignore[arg-type]
            idempotency_key=payload.get("idempotency_key"),  # type: ignore[arg-type]
            observed_at=_optional_text(payload.get("observed_at"), "observed_at"),
        )

    def content(self) -> str:
        return json.dumps(
            {
                "options": list(self.options),
                "recommendation": self.recommendation,
                "explicit_answer": self.explicit_answer,
                "rationale": self.rationale,
            },
            sort_keys=True,
        )

    def to_mapping(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""

        return {
            "hospital_id": self.hospital_id,
            "strategy_version": self.strategy_version,
            "options": list(self.options),
            "recommendation": self.recommendation,
            "explicit_answer": self.explicit_answer,
            "rationale": self.rationale,
            "author_agent": self.author_agent,
            "idempotency_key": self.idempotency_key,
            "observed_at": self.observed_at,
        }


@dataclass(frozen=True, slots=True)
class IndexHit:
    """A result returned by a memory index before canonical lookup."""

    record_id: str
    score: float
    evidence: str | None = None


@dataclass(frozen=True, slots=True)
class RecallMatch:
    """A validated canonical record returned from recall."""

    record: MemoryRecord
    score: float
    evidence: str | None = None

    def to_mapping(self) -> dict[str, object]:
        return {
            "record": self.record.to_mapping(),
            "score": self.score,
            "evidence": self.evidence,
        }


@dataclass(frozen=True, slots=True)
class RememberResult:
    """Result of a remember operation."""

    record_id: str
    indexing_state: IndexingState
    error: str | None
    created: bool

    def to_mapping(self) -> dict[str, object]:
        return {
            "record_id": self.record_id,
            "indexing_state": self.indexing_state.value,
            "error": self.error,
            "created": self.created,
        }


@dataclass(frozen=True, slots=True)
class RecallResult:
    """Result of a hospital-scoped recall operation."""

    hospital_id: str
    query: str
    matches: tuple[RecallMatch, ...]

    def to_mapping(self) -> dict[str, object]:
        return {
            "hospital_id": self.hospital_id,
            "query": self.query,
            "matches": [match.to_mapping() for match in self.matches],
        }
