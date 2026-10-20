"""SQLite-backed canonical record store."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, cast

from hospital_gtm.models import (
    DecisionRequest,
    EvidenceStatus,
    IndexHit,
    IndexingState,
    MemoryRecord,
    ModelValidationError,
    RecordKind,
)


class StoreError(RuntimeError):
    """Base error for canonical store failures."""


class RecordNotFound(StoreError):
    """Raised when a requested record does not exist."""


class IdempotencyConflict(StoreError):
    """Raised when an idempotency key is reused for a different payload."""


class InvalidRecordReference(StoreError):
    """Raised when a record references missing or cross-hospital records."""


class SQLiteRecordStore:
    """Persist canonical memory records and decision metadata in SQLite."""

    def __init__(self, database_path: str | Path) -> None:
        """Initialize the SQLite record store.

        Args:
            database_path: SQLite path or `:memory:`.
        """
        self.database_path = str(database_path)
        if self.database_path != ":memory:":
            Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._memory_connection: sqlite3.Connection | None = None
        if self.database_path == ":memory:":
            self._memory_connection = sqlite3.connect(
                self.database_path,
                timeout=30,
                isolation_level=None,
                check_same_thread=False,
            )
            self._memory_connection.row_factory = sqlite3.Row
        self._initialize()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        """Yield a configured SQLite connection.

        Returns:
            A SQLite connection context.
        """
        if self._memory_connection is not None:
            yield self._memory_connection
            return
        connection = sqlite3.connect(
            self.database_path,
            timeout=30,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        if self.database_path != ":memory:":
            connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        """Create the canonical store schema."""
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS records (
                    record_id TEXT PRIMARY KEY,
                    hospital_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    content TEXT NOT NULL,
                    evidence_status TEXT NOT NULL,
                    author_agent TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    source_url TEXT,
                    source_file TEXT,
                    source_title TEXT,
                    observed_at TEXT,
                    created_at TEXT NOT NULL,
                    source_record_ids_json TEXT NOT NULL,
                    strategy_version TEXT,
                    supersedes_record_id TEXT,
                    indexing_state TEXT NOT NULL,
                    indexing_error TEXT
                );

                CREATE INDEX IF NOT EXISTS records_hospital_idx
                    ON records (hospital_id, created_at);

                CREATE TABLE IF NOT EXISTS record_links (
                    record_id TEXT NOT NULL REFERENCES records(record_id),
                    source_record_id TEXT NOT NULL REFERENCES records(record_id),
                    PRIMARY KEY (record_id, source_record_id)
                );

                CREATE TABLE IF NOT EXISTS decisions (
                    decision_id TEXT PRIMARY KEY,
                    hospital_id TEXT NOT NULL,
                    strategy_version TEXT NOT NULL,
                    options_json TEXT NOT NULL,
                    recommendation TEXT NOT NULL,
                    explicit_answer TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    decided_at TEXT NOT NULL,
                    author_agent TEXT NOT NULL,
                    record_id TEXT NOT NULL UNIQUE REFERENCES records(record_id)
                );
                """
            )

    def remember(self, record: MemoryRecord) -> tuple[MemoryRecord, bool]:
        """Insert a record or return the existing retry record.

        Args:
            record: Record to persist.

        Returns:
            The stored record and whether it was newly created.
        """

        with self._lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing_row = connection.execute(
                "SELECT * FROM records WHERE idempotency_key = ?",
                (record.idempotency_key,),
            ).fetchone()
            if existing_row is not None:
                existing = self._row_to_record(existing_row)
                if existing.payload_mapping() != record.payload_mapping():
                    connection.execute("ROLLBACK")
                    raise IdempotencyConflict(
                        f"idempotency key already belongs to {existing.record_id}"
                    )
                connection.execute("COMMIT")
                return existing, False

            try:
                self._validate_references(connection, record)
                connection.execute(
                    """
                    INSERT INTO records (
                        record_id, hospital_id, kind, content, evidence_status,
                        author_agent, idempotency_key, source_url, source_file,
                        source_title, observed_at, created_at,
                        source_record_ids_json, strategy_version,
                        supersedes_record_id, indexing_state, indexing_error
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.record_id,
                        record.hospital_id,
                        record.kind.value,
                        record.content,
                        record.evidence_status.value,
                        record.author_agent,
                        record.idempotency_key,
                        record.source_url,
                        record.source_file,
                        record.source_title,
                        record.observed_at,
                        record.created_at,
                        json.dumps(list(record.source_record_ids)),
                        record.strategy_version,
                        record.supersedes_record_id,
                        record.indexing_state.value,
                        record.indexing_error,
                    ),
                )
                connection.executemany(
                    "INSERT INTO record_links (record_id, source_record_id) VALUES (?, ?)",
                    [
                        (record.record_id, source_id)
                        for source_id in record.source_record_ids
                    ],
                )
                connection.execute("COMMIT")
            except sqlite3.IntegrityError as exc:
                connection.execute("ROLLBACK")
                raise StoreError(str(exc)) from exc
            except Exception:
                connection.execute("ROLLBACK")
                raise
            return record, True

    def get(self, record_id: str) -> MemoryRecord:
        """Return a canonical record by stable ID.

        Args:
            record_id: Stable record identifier.

        Returns:
            The canonical record.
        """

        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM records WHERE record_id = ?", (record_id,)
            ).fetchone()
        if row is None:
            raise RecordNotFound(f"record not found: {record_id}")
        return self._row_to_record(row)

    def list_records(
        self,
        hospital_id: str,
        kind: RecordKind | None = None,
    ) -> tuple[MemoryRecord, ...]:
        """Return all ready records for a hospital and optional kind.

        Args:
            hospital_id: Hospital namespace for the records.
            kind: Optional record kind filter.

        Returns:
            Canonical records ordered by creation time.
        """
        query = """
            SELECT * FROM records
            WHERE hospital_id = ? AND indexing_state = ?
        """
        parameters: list[str] = [hospital_id, IndexingState.READY.value]
        if kind is not None:
            query += " AND kind = ?"
            parameters.append(kind.value)
        query += " ORDER BY created_at ASC, record_id ASC"
        with self._connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return tuple(self._row_to_record(row) for row in rows)

    def set_indexing_state(
        self,
        record_id: str,
        state: IndexingState,
        error: str | None = None,
    ) -> MemoryRecord:
        """Update indexing state after an index attempt.

        Args:
            record_id: Stable record identifier.
            state: New indexing state.
            error: Optional indexing error.

        Returns:
            The updated record.
        """

        with self._lock, self._connection() as connection:
            connection.execute(
                """
                UPDATE records
                SET indexing_state = ?, indexing_error = ?
                WHERE record_id = ?
                """,
                (state.value, error, record_id),
            )
        return self.get(record_id)

    def keyword_search(
        self,
        hospital_id: str,
        query: str,
        limit: int,
    ) -> tuple[IndexHit, ...]:
        """Search ready records with the local fallback index.

        Args:
            hospital_id: Hospital scope for the search.
            query: Search terms.
            limit: Maximum number of matches.

        Returns:
            Matching index hits.
        """

        if limit < 1:
            raise ModelValidationError("limit must be at least 1")
        tokens = tuple(dict.fromkeys(re.findall(r"[a-z0-9_]+", query.lower())))
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM records
                WHERE hospital_id = ? AND indexing_state = ?
                ORDER BY created_at ASC
                """,
                (hospital_id, IndexingState.READY.value),
            ).fetchall()

        hits: list[IndexHit] = []
        for row in rows:
            record = self._row_to_record(row)
            haystack = " ".join(
                value or ""
                for value in (
                    record.hospital_id,
                    record.kind.value,
                    record.evidence_status.value,
                    record.content,
                    record.source_title,
                    record.source_url,
                    record.source_file,
                )
            ).lower()
            score = sum(haystack.count(token) for token in tokens)
            if not tokens:
                score = 1
            if score:
                hits.append(
                    IndexHit(
                        record_id=record.record_id,
                        score=float(score),
                        evidence=record.content,
                    )
                )
        hits.sort(key=lambda hit: (-hit.score, hit.record_id))
        return tuple(hits[:limit])

    def save_decision(
        self,
        decision_id: str,
        decision: DecisionRequest,
        record_id: str,
    ) -> None:
        """Store structured decision fields beside its record.

        Args:
            decision_id: Stable decision identifier.
            decision: Decision fields to persist.
            record_id: Linked canonical record identifier.
        """

        with self._lock, self._connection() as connection:
            try:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO decisions (
                        decision_id, hospital_id, strategy_version, options_json,
                        recommendation, explicit_answer, rationale, decided_at,
                        author_agent, record_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        decision_id,
                        decision.hospital_id,
                        decision.strategy_version,
                        json.dumps(list(decision.options)),
                        decision.recommendation,
                        decision.explicit_answer,
                        decision.rationale,
                        decision.observed_at or datetime.now(timezone.utc).isoformat(),
                        decision.author_agent,
                        record_id,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise StoreError(str(exc)) from exc

    def _validate_references(
        self,
        connection: sqlite3.Connection,
        record: MemoryRecord,
    ) -> None:
        """Validate record references and hospital ownership.

        Args:
            connection: Active SQLite connection.
            record: Record whose references are checked.
        """
        reference_ids = (*record.source_record_ids, record.supersedes_record_id)
        for reference_id in reference_ids:
            if reference_id is None:
                continue
            row = connection.execute(
                "SELECT hospital_id FROM records WHERE record_id = ?",
                (reference_id,),
            ).fetchone()
            if row is None:
                raise InvalidRecordReference(f"record not found: {reference_id}")
            if cast(str, row["hospital_id"]) != record.hospital_id:
                raise InvalidRecordReference(
                    f"record {reference_id} belongs to another hospital"
                )

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> MemoryRecord:
        """Convert a SQLite row into a memory record.

        Args:
            row: SQLite record row.

        Returns:
            The decoded memory record.
        """
        source_record_ids = json.loads(cast(str, row["source_record_ids_json"]))
        if not isinstance(source_record_ids, list) or not all(
            isinstance(item, str) for item in source_record_ids
        ):
            raise StoreError("invalid source_record_ids_json in database")
        return MemoryRecord(
            record_id=cast(str, row["record_id"]),
            hospital_id=cast(str, row["hospital_id"]),
            kind=RecordKind(cast(str, row["kind"])),
            content=cast(str, row["content"]),
            evidence_status=EvidenceStatus(cast(str, row["evidence_status"])),
            author_agent=cast(str, row["author_agent"]),
            idempotency_key=cast(str, row["idempotency_key"]),
            source_url=cast(str | None, row["source_url"]),
            source_file=cast(str | None, row["source_file"]),
            source_title=cast(str | None, row["source_title"]),
            observed_at=cast(str | None, row["observed_at"]),
            created_at=cast(str, row["created_at"]),
            source_record_ids=tuple(source_record_ids),
            strategy_version=cast(str | None, row["strategy_version"]),
            supersedes_record_id=cast(str | None, row["supersedes_record_id"]),
            indexing_state=IndexingState(cast(str, row["indexing_state"])),
            indexing_error=cast(str | None, row["indexing_error"]),
        )
