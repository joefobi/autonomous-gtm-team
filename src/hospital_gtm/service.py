"""Shared memory service and loopback HTTP API."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast
from urllib.parse import parse_qs, unquote, urlsplit

from hospital_gtm.index import KeywordIndex, MemoryIndex
from hospital_gtm.models import (
    DecisionRequest,
    EvidenceStatus,
    IndexingState,
    MemoryRecord,
    ModelValidationError,
    RecallMatch,
    RecallResult,
    RecordKind,
    RememberResult,
)
from hospital_gtm.store import (
    IdempotencyConflict,
    InvalidRecordReference,
    RecordNotFound,
    SQLiteRecordStore,
    StoreError,
)

MAX_REQUEST_BODY_BYTES = 1_048_576
REQUEST_READ_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True, slots=True)
class DecisionResult:
    """Result of recording an explicit founder decision."""

    decision_id: str
    record_id: str
    strategy_version: str
    indexing_state: IndexingState
    error: str | None

    def to_mapping(self) -> dict[str, object]:
        """Return JSON-compatible decision result fields.

        Returns:
            Serialized decision result.
        """
        return {
            "decision_id": self.decision_id,
            "record_id": self.record_id,
            "strategy_version": self.strategy_version,
            "indexing_state": self.indexing_state.value,
            "error": self.error,
        }


class MemoryService:
    """Coordinate canonical persistence and index updates."""

    def __init__(
        self,
        store: SQLiteRecordStore,
        index: MemoryIndex | None = None,
    ) -> None:
        """Initialize the memory service.

        Args:
            store: Canonical SQLite store.
            index: Optional memory index.
        """
        self.store = store
        self.index = index or KeywordIndex(store)

    def remember(self, record: MemoryRecord) -> RememberResult:
        """Persist and index a memory record.

        Args:
            record: Record to persist.

        Returns:
            The indexing result.
        """
        stored, created = self.store.remember(record)
        if not created and stored.indexing_state is IndexingState.READY:
            return RememberResult(
                record_id=stored.record_id,
                indexing_state=stored.indexing_state,
                error=stored.indexing_error,
                created=False,
            )

        try:
            self.index.index(stored)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            failed = self.store.set_indexing_state(
                stored.record_id,
                IndexingState.FAILED,
                error,
            )
            return RememberResult(
                record_id=failed.record_id,
                indexing_state=failed.indexing_state,
                error=failed.indexing_error,
                created=created,
            )

        ready = self.store.set_indexing_state(stored.record_id, IndexingState.READY)
        return RememberResult(
            record_id=ready.record_id,
            indexing_state=ready.indexing_state,
            error=ready.indexing_error,
            created=created,
        )

    def get_record(self, record_id: str) -> MemoryRecord:
        """Retrieve a canonical record.

        Args:
            record_id: Stable record identifier.

        Returns:
            The canonical record.
        """
        return self.store.get(record_id)

    def list_records(
        self,
        hospital_id: str,
        kind: RecordKind | None = None,
    ) -> tuple[MemoryRecord, ...]:
        """List ready canonical records for a hospital.

        Args:
            hospital_id: Hospital namespace for the records.
            kind: Optional record kind filter.

        Returns:
            Canonical records ordered by creation time.
        """
        if not hospital_id.strip():
            raise ModelValidationError("hospital_id must be a non-empty string")
        return self.store.list_records(hospital_id.strip(), kind)

    def recall(self, hospital_id: str, query: str, limit: int = 20) -> RecallResult:
        """Recall indexed records for a hospital.

        Args:
            hospital_id: Hospital scope for the search.
            query: Search question or terms.
            limit: Maximum number of matches.

        Returns:
            Matching canonical records.
        """
        if not hospital_id.strip():
            raise ModelValidationError("hospital_id must be a non-empty string")
        if limit < 1 or limit > 100:
            raise ModelValidationError("limit must be between 1 and 100")
        hits = self.index.recall(hospital_id.strip(), query, limit)
        matches: list[RecallMatch] = []
        for hit in hits:
            try:
                record = self.store.get(hit.record_id)
            except RecordNotFound:
                continue
            if record.hospital_id != hospital_id.strip():
                continue
            if record.indexing_state is not IndexingState.READY:
                continue
            matches.append(RecallMatch(record, hit.score, hit.evidence))
        return RecallResult(hospital_id.strip(), query, tuple(matches))

    def record_decision(self, decision: DecisionRequest) -> DecisionResult:
        """Persist and index a founder decision.

        Args:
            decision: Decision to persist.

        Returns:
            The decision indexing result.
        """
        record_id = (
            f"decision_{uuid.uuid5(uuid.NAMESPACE_URL, decision.idempotency_key).hex}"
        )
        record = MemoryRecord(
            record_id=record_id,
            hospital_id=decision.hospital_id,
            kind=RecordKind.FOUNDER_DECISION,
            content=decision.content(),
            evidence_status=EvidenceStatus.FOUNDER_CONFIRMED,
            author_agent=decision.author_agent,
            idempotency_key=decision.idempotency_key,
            observed_at=decision.observed_at,
            strategy_version=decision.strategy_version,
        )
        remember_result = self.remember(record)
        decision_id = f"decision_{remember_result.record_id}"
        self.store.save_decision(decision_id, decision, remember_result.record_id)
        return DecisionResult(
            decision_id=decision_id,
            record_id=remember_result.record_id,
            strategy_version=decision.strategy_version,
            indexing_state=remember_result.indexing_state,
            error=remember_result.error,
        )

    def health(self) -> dict[str, object]:
        """Return service health details.

        Returns:
            Health status and storage details.
        """
        return {
            "status": "ok",
            "database": self.store.database_path,
            "index": type(self.index).__name__,
        }


def create_server(
    service: MemoryService,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> ThreadingHTTPServer:
    """Create an HTTP server without starting its event loop.

    Args:
        service: Memory service to expose.
        host: Interface to bind.
        port: Port to bind.

    Returns:
        Configured HTTP server.
    """

    handler = _handler_for(service)
    return ThreadingHTTPServer((host, port), handler)


def serve(service: MemoryService, host: str = "127.0.0.1", port: int = 8765) -> None:
    """Run the memory service until interrupted.

    Args:
        service: Memory service to expose.
        host: Interface to bind.
        port: Port to bind.
    """

    server = create_server(service, host, port)
    try:
        server.serve_forever()
    finally:
        server.server_close()


def _handler_for(service: MemoryService) -> type[BaseHTTPRequestHandler]:
    """Build an HTTP handler bound to a memory service.

    Args:
        service: Memory service for request handling.

    Returns:
        A configured request handler class.
    """

    class MemoryRequestHandler(BaseHTTPRequestHandler):
        server_version = "HospitalGTM/0.1"

        def setup(self) -> None:
            """Configure the request socket timeout."""
            super().setup()
            self.connection.settimeout(REQUEST_READ_TIMEOUT_SECONDS)

        def do_GET(self) -> None:
            """Handle health and record GET requests."""
            parsed_path = urlsplit(self.path)
            path = parsed_path.path
            try:
                if path == "/health":
                    self._send_json(200, service.health())
                    return
                if path == "/memories":
                    query = parse_qs(parsed_path.query)
                    hospital_id = _query_value(query, "hospital_id")
                    kind_value = _optional_query_value(query, "kind")
                    kind = RecordKind(kind_value) if kind_value else None
                    records = service.list_records(hospital_id, kind)
                    self._send_json(
                        200,
                        {"records": [record.to_mapping() for record in records]},
                    )
                    return
                prefix = "/memories/"
                if path.startswith(prefix) and path != prefix:
                    record = service.get_record(unquote(path[len(prefix) :]))
                    self._send_json(200, record.to_mapping())
                    return
                self._send_json(404, {"error": "endpoint not found"})
            except Exception as exc:
                self._send_error(exc)

        def do_POST(self) -> None:
            """Handle memory, recall, and decision POST requests."""
            path = urlsplit(self.path).path
            try:
                payload = self._read_json()
                if path == "/memories":
                    record = MemoryRecord.from_mapping(_record_payload(payload))
                    result = service.remember(record)
                    self._send_json(200, result.to_mapping())
                    return
                if path == "/recall":
                    hospital_id, query, limit = _recall_payload(payload)
                    self._send_json(
                        200, service.recall(hospital_id, query, limit).to_mapping()
                    )
                    return
                if path == "/decisions":
                    decision = DecisionRequest.from_mapping(payload)
                    self._send_json(200, service.record_decision(decision).to_mapping())
                    return
                self._send_json(404, {"error": "endpoint not found"})
            except Exception as exc:
                self._send_error(exc)

        def _read_json(self) -> dict[str, object]:
            """Read and validate a JSON request body.

            Returns:
                Decoded JSON object.
            """
            content_length = self.headers.get("Content-Length")
            if content_length is None:
                raise ModelValidationError("Content-Length header is required")
            try:
                length = int(content_length)
            except ValueError as exc:
                raise ModelValidationError("Content-Length must be an integer") from exc
            if length < 0:
                raise ModelValidationError("Content-Length must not be negative")
            if length > MAX_REQUEST_BODY_BYTES:
                raise ModelValidationError(
                    f"request body must not exceed {MAX_REQUEST_BODY_BYTES} bytes"
                )
            try:
                decoded = json.loads(self.rfile.read(length))
            except json.JSONDecodeError as exc:
                raise ModelValidationError("request body must be valid JSON") from exc
            if not isinstance(decoded, dict):
                raise ModelValidationError("request body must be a JSON object")
            return cast(dict[str, object], decoded)

        def _send_json(self, status: int, payload: Mapping[str, object]) -> None:
            """Send a JSON response.

            Args:
                status: HTTP status code.
                payload: JSON response fields.
            """
            body = json.dumps(payload, sort_keys=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_error(self, error: Exception) -> None:
            """Send an error response.

            Args:
                error: Exception to serialize.
            """
            if isinstance(error, (ModelValidationError, ValueError)):
                status = 400
            elif isinstance(error, RecordNotFound):
                status = 404
            elif isinstance(error, IdempotencyConflict):
                status = 409
            elif isinstance(error, InvalidRecordReference):
                status = 422
            elif isinstance(error, StoreError):
                status = 500
            else:
                status = 500
            self._send_json(status, {"error": str(error)})

        def log_message(self, format: str, *args: Any) -> None:
            """Suppress default request logging.

            Args:
                format: Logging format string.
                args: Logging arguments.
            """
            del format, args

    return MemoryRequestHandler


def _record_payload(payload: Mapping[str, object]) -> dict[str, object]:
    """Extract a record payload from a request.

    Args:
        payload: Decoded request payload.

    Returns:
        Record fields with the idempotency key.
    """
    raw_record = payload.get("record", payload)
    if not isinstance(raw_record, dict):
        raise ModelValidationError("record must be a JSON object")
    record = dict(cast(dict[str, object], raw_record))
    top_level_key = payload.get("idempotency_key")
    if "idempotency_key" not in record and top_level_key is not None:
        record["idempotency_key"] = top_level_key
    return record


def _recall_payload(payload: Mapping[str, object]) -> tuple[str, str, int]:
    """Validate recall request fields.

    Args:
        payload: Decoded request payload.

    Returns:
        Hospital ID, query, and result limit.
    """
    hospital_id = payload.get("hospital_id")
    query = payload.get("query", "")
    limit = payload.get("limit", 20)
    if not isinstance(hospital_id, str):
        raise ModelValidationError("hospital_id must be a string")
    if not isinstance(query, str):
        raise ModelValidationError("query must be a string")
    if not isinstance(limit, int):
        raise ModelValidationError("limit must be an integer")
    return hospital_id, query, limit


def _query_value(query: Mapping[str, list[str]], field_name: str) -> str:
    """Read one required query-string value.

    Args:
        query: Parsed query-string fields.
        field_name: Field to read.

    Returns:
        Non-empty query value.
    """
    values = query.get(field_name)
    if not values or not values[0].strip():
        raise ModelValidationError(f"{field_name} query parameter is required")
    return values[0]


def _optional_query_value(
    query: Mapping[str, list[str]],
    field_name: str,
) -> str | None:
    """Read one optional query-string value.

    Args:
        query: Parsed query-string fields.
        field_name: Field to read.

    Returns:
        Query value or `None` when absent.
    """
    values = query.get(field_name)
    if not values:
        return None
    if not values[0].strip():
        raise ModelValidationError(f"{field_name} query parameter must not be empty")
    return values[0]
