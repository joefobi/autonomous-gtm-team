"""Pluggable memory indexes for local and Cognee-backed recall."""

from __future__ import annotations

import asyncio
import importlib
import inspect
import re
from collections.abc import Mapping
from typing import Awaitable, Callable, Protocol, cast

from hospital_gtm.models import IndexHit, MemoryRecord
from hospital_gtm.store import SQLiteRecordStore


class IndexError(RuntimeError):
    """Raised when a memory index cannot process a record."""


class MemoryIndex(Protocol):
    """Interface implemented by keyword and semantic indexes."""

    def index(self, record: MemoryRecord) -> None:
        """Add a record to the index.

        Args:
            record: Record to index.
        """

    def recall(self, hospital_id: str, query: str, limit: int) -> tuple[IndexHit, ...]:
        """Return candidate canonical record IDs.

        Args:
            hospital_id: Hospital scope for the search.
            query: Search question or terms.
            limit: Maximum number of candidates.

        Returns:
            Candidate index hits.
        """


class KeywordIndex:
    """Deterministic SQLite-backed fallback used without external services."""

    def __init__(self, store: SQLiteRecordStore) -> None:
        """Initialize the keyword index.

        Args:
            store: Canonical SQLite store.
        """
        self._store = store

    def index(self, record: MemoryRecord) -> None:
        """Accept a record for the SQLite-backed index.

        Args:
            record: Record already stored in SQLite.
        """
        del record

    def recall(self, hospital_id: str, query: str, limit: int) -> tuple[IndexHit, ...]:
        """Search the local keyword index.

        Args:
            hospital_id: Hospital scope for the search.
            query: Search question or terms.
            limit: Maximum number of matches.

        Returns:
            Matching index hits.
        """
        return self._store.keyword_search(hospital_id, query, limit)


class CogneeIndex:
    """Adapter for Cognee's remember/recall API.

    Cognee is intentionally optional. The adapter imports it only when selected
    so the local service and its tests remain usable without model downloads.
    """

    def __init__(self, dataset_name: str, cognee_module: object | None = None) -> None:
        """Initialize the Cognee adapter.

        Args:
            dataset_name: Cognee dataset name.
            cognee_module: Optional injected Cognee module.
        """
        if not dataset_name.strip():
            raise ValueError("dataset_name must be non-empty")
        self.dataset_name = dataset_name
        self._cognee_module = cognee_module

    def _module(self) -> object:
        """Load the configured Cognee module.

        Returns:
            The Cognee module.
        """
        if self._cognee_module is None:
            try:
                self._cognee_module = importlib.import_module("cognee")
            except ModuleNotFoundError as exc:
                raise IndexError(
                    "Cognee is not installed; use KeywordIndex or install Cognee"
                ) from exc
        return self._cognee_module

    def index(self, record: MemoryRecord) -> None:
        """Index a record in Cognee.

        Args:
            record: Record to index.
        """
        remember = getattr(self._module(), "remember", None)
        if not callable(remember):
            raise IndexError("configured Cognee module has no remember function")
        self._resolve(
            cast(Callable[..., object], remember)(
                record.index_text(), dataset_name=self.dataset_name
            )
        )

    def recall(self, hospital_id: str, query: str, limit: int) -> tuple[IndexHit, ...]:
        """Recall candidate records from Cognee.

        Args:
            hospital_id: Hospital scope for the search.
            query: Search question or terms.
            limit: Maximum number of matches.

        Returns:
            Candidate index hits.
        """
        recall = getattr(self._module(), "recall", None)
        if not callable(recall):
            raise IndexError("configured Cognee module has no recall function")
        result = self._resolve(
            cast(Callable[..., object], recall)(
                f"hospital_id: {hospital_id}\nquery: {query}",
                datasets=[self.dataset_name],
            )
        )
        hits: dict[str, IndexHit] = {}
        self._collect_hits(result, hits)
        return tuple(
            sorted(hits.values(), key=lambda hit: (-hit.score, hit.record_id))[:limit]
        )

    @staticmethod
    def _resolve(value: object) -> object:
        """Resolve a synchronous or asynchronous Cognee result.

        Args:
            value: Cognee return value.

        Returns:
            The resolved value.
        """
        if inspect.isawaitable(value):
            return asyncio.run(_await_value(cast(Awaitable[object], value)))
        return value

    @classmethod
    def _collect_hits(
        cls,
        value: object,
        hits: dict[str, IndexHit],
        evidence: str | None = None,
    ) -> None:
        """Collect record IDs from a Cognee response.

        Args:
            value: Nested Cognee response value.
            hits: Mutable hit collection.
            evidence: Inherited evidence text.
        """
        for method_name in ("model_dump", "dict"):
            method = getattr(value, method_name, None)
            if callable(method):
                dumped = method()
                if dumped is not value:
                    cls._collect_hits(dumped, hits, evidence)
                return
        if isinstance(value, Mapping):
            record_id = value.get("record_id")
            if isinstance(record_id, str) and record_id.strip():
                score_value = value.get("score", 1.0)
                score = (
                    float(score_value) if isinstance(score_value, (int, float)) else 1.0
                )
                evidence_value = value.get("content", evidence)
                hit_evidence = (
                    evidence_value if isinstance(evidence_value, str) else evidence
                )
                hits[record_id] = IndexHit(record_id, score, hit_evidence)
            for nested in value.values():
                cls._collect_hits(nested, hits, evidence)
            return
        if isinstance(value, (list, tuple, set)):
            for nested in value:
                cls._collect_hits(nested, hits, evidence)
            return
        if isinstance(value, str):
            for record_id in re.findall(r"record_id\s*[:=]\s*([\w.-]+)", value):
                hits[record_id] = IndexHit(record_id, 1.0, value)


async def _await_value(value: Awaitable[object]) -> object:
    """Await a Cognee result.

    Args:
        value: Awaitable result.

    Returns:
        The awaited value.
    """
    return await value
