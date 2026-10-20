"""HTTP client for the shared memory service."""

from __future__ import annotations

import json
from collections.abc import Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from hospital_gtm.models import (
    DecisionRequest,
    IndexingState,
    MemoryRecord,
    RecallMatch,
    RecallResult,
    RememberResult,
)


class MemoryClientError(RuntimeError):
    """Raised when the memory service cannot satisfy a client request."""


class MemoryClient:
    """Small dependency-free client for the local HTTP API."""

    def __init__(self, base_url: str, timeout: float = 30.0) -> None:
        """Initialize the HTTP client.

        Args:
            base_url: Memory service URL.
            timeout: Request timeout in seconds.
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def remember(self, record: MemoryRecord) -> RememberResult:
        """Store a memory record.

        Args:
            record: Record to store.

        Returns:
            The indexing result.
        """
        payload = self._request("POST", "/memories", {"record": record.to_mapping()})
        return RememberResult(
            record_id=_required_string(payload, "record_id"),
            indexing_state=IndexingState(_required_string(payload, "indexing_state")),
            error=_optional_string(payload, "error"),
            created=_required_bool(payload, "created"),
        )

    def get_record(self, record_id: str) -> MemoryRecord:
        """Fetch a canonical record.

        Args:
            record_id: Stable record identifier.

        Returns:
            The canonical record.
        """
        payload = self._request("GET", f"/memories/{quote(record_id, safe='')}")
        return MemoryRecord.from_mapping(payload)

    def recall(self, hospital_id: str, query: str, limit: int = 20) -> RecallResult:
        """Recall records for a hospital.

        Args:
            hospital_id: Hospital scope for the search.
            query: Search question or terms.
            limit: Maximum number of matches.

        Returns:
            Matching canonical records.
        """
        payload = self._request(
            "POST",
            "/recall",
            {"hospital_id": hospital_id, "query": query, "limit": limit},
        )
        raw_matches = payload.get("matches")
        if not isinstance(raw_matches, list):
            raise MemoryClientError("recall response has invalid matches")
        matches: list[RecallMatch] = []
        for raw_match in raw_matches:
            if not isinstance(raw_match, dict):
                raise MemoryClientError("recall response has an invalid match")
            raw_record = raw_match.get("record")
            if not isinstance(raw_record, dict):
                raise MemoryClientError("recall response has an invalid record")
            score = raw_match.get("score")
            if not isinstance(score, (int, float)):
                raise MemoryClientError("recall response has an invalid score")
            evidence = raw_match.get("evidence")
            if evidence is not None and not isinstance(evidence, str):
                raise MemoryClientError("recall response has invalid evidence")
            matches.append(
                RecallMatch(
                    record=MemoryRecord.from_mapping(raw_record),
                    score=float(score),
                    evidence=evidence,
                )
            )
        return RecallResult(
            hospital_id=_required_string(payload, "hospital_id"),
            query=_required_string(payload, "query"),
            matches=tuple(matches),
        )

    def health(self) -> dict[str, object]:
        """Fetch service health.

        Returns:
            Service health details.
        """
        return self._request("GET", "/health")

    def record_decision(self, decision: DecisionRequest) -> dict[str, object]:
        """Record a founder decision.

        Args:
            decision: Decision to persist.

        Returns:
            The service response.
        """
        return self._request("POST", "/decisions", decision.to_mapping())

    def _request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        """Send an HTTP request to the memory service.

        Args:
            method: HTTP method.
            path: Service-relative path.
            payload: Optional JSON request body.

        Returns:
            The decoded JSON response.
        """
        body = None
        headers: dict[str, str] = {}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(
            f"{self.base_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw_response = response.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise MemoryClientError(
                f"memory service returned {exc.code}: {detail}"
            ) from exc
        except URLError as exc:
            raise MemoryClientError(
                f"could not reach memory service: {exc.reason}"
            ) from exc
        try:
            decoded = json.loads(raw_response)
        except json.JSONDecodeError as exc:
            raise MemoryClientError("memory service returned invalid JSON") from exc
        if not isinstance(decoded, dict):
            raise MemoryClientError("memory service returned a non-object JSON value")
        return decoded


def _required_string(payload: Mapping[str, object], field_name: str) -> str:
    """Read a required string response field.

    Args:
        payload: Decoded response payload.
        field_name: Field to read.

    Returns:
        The field value.
    """
    value = payload.get(field_name)
    if not isinstance(value, str):
        raise MemoryClientError(f"response field {field_name} must be a string")
    return value


def _optional_string(payload: Mapping[str, object], field_name: str) -> str | None:
    """Read an optional string response field.

    Args:
        payload: Decoded response payload.
        field_name: Field to read.

    Returns:
        The field value or `None`.
    """
    value = payload.get(field_name)
    if value is not None and not isinstance(value, str):
        raise MemoryClientError(f"response field {field_name} must be a string or null")
    return value


def _required_bool(payload: Mapping[str, object], field_name: str) -> bool:
    """Read a required boolean response field.

    Args:
        payload: Decoded response payload.
        field_name: Field to read.

    Returns:
        The field value.
    """
    value = payload.get(field_name)
    if not isinstance(value, bool):
        raise MemoryClientError(f"response field {field_name} must be a boolean")
    return value
