from __future__ import annotations

import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from urllib.request import urlopen

from hospital_gtm.client import MemoryClient
from hospital_gtm.models import (
    DecisionRequest,
    EvidenceStatus,
    IndexingState,
    MemoryRecord,
    RecordKind,
)
from hospital_gtm.service import MemoryService, create_server
from hospital_gtm.store import (
    IdempotencyConflict,
    InvalidRecordReference,
    SQLiteRecordStore,
)


def make_record(
    record_id: str,
    hospital_id: str = "demo",
    content: str = "The hospital is evaluating patient flow priorities.",
) -> MemoryRecord:
    """Build a sourced memory record for tests.

    Args:
        record_id: Identifier for the record.
        hospital_id: Hospital namespace for the record.
        content: Text stored in the record.

    Returns:
        A valid test memory record.
    """
    return MemoryRecord(
        record_id=record_id,
        hospital_id=hospital_id,
        kind=RecordKind.PUBLIC_EVIDENCE,
        content=content,
        evidence_status=EvidenceStatus.SOURCED,
        author_agent="researcher",
        idempotency_key=f"test:{record_id}",
        source_file="tests/fixture.md",
        source_title="Test source",
    )


class MemoryServiceTests(unittest.TestCase):
    def test_persists_across_store_instances_and_recalls(self) -> None:
        """Persist and recall records across store instances."""
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "memory.sqlite3"
            service = MemoryService(SQLiteRecordStore(database_path))
            result = service.remember(make_record("record_001"))

            self.assertTrue(result.created)
            self.assertEqual(result.indexing_state, IndexingState.READY)

            fresh_store = SQLiteRecordStore(database_path)
            stored = fresh_store.get("record_001")
            self.assertEqual(
                stored.content, "The hospital is evaluating patient flow priorities."
            )
            recalled = MemoryService(fresh_store).recall("demo", "patient flow")
            self.assertEqual(
                [match.record.record_id for match in recalled.matches], ["record_001"]
            )

    def test_recall_isolated_by_hospital(self) -> None:
        """Keep recall results isolated by hospital."""
        service = MemoryService(SQLiteRecordStore(":memory:"))
        service.remember(make_record("demo_001", hospital_id="demo"))
        service.remember(make_record("other_001", hospital_id="other"))

        recalled = service.recall("demo", "patient flow")

        self.assertEqual(
            [match.record.hospital_id for match in recalled.matches], ["demo"]
        )

    def test_idempotency_returns_existing_record_and_rejects_conflicts(self) -> None:
        """Return existing records and reject conflicting retries."""
        service = MemoryService(SQLiteRecordStore(":memory:"))
        record = make_record("record_001")

        first = service.remember(record)
        retry = service.remember(record)

        self.assertTrue(first.created)
        self.assertFalse(retry.created)
        self.assertEqual(first.record_id, retry.record_id)

        with self.assertRaises(IdempotencyConflict):
            service.remember(replace(record, record_id="record_002"))

    def test_rejects_missing_and_cross_hospital_references(self) -> None:
        """Reject missing and cross-hospital record references."""
        store = SQLiteRecordStore(":memory:")
        service = MemoryService(store)
        with self.assertRaises(InvalidRecordReference):
            service.remember(
                replace(make_record("derived_001"), source_record_ids=("missing",))
            )

        service.remember(make_record("other_001", hospital_id="other"))
        with self.assertRaises(InvalidRecordReference):
            service.remember(
                replace(make_record("derived_002"), source_record_ids=("other_001",))
            )

    def test_records_explicit_decision(self) -> None:
        """Persist explicit founder decisions."""
        service = MemoryService(SQLiteRecordStore(":memory:"))
        decision = DecisionRequest(
            hospital_id="demo",
            strategy_version="strategy_v1",
            options=("interview operations", "defer"),
            recommendation="interview operations",
            explicit_answer="approved",
            rationale="The public evidence supports a discovery conversation, not a product claim.",
            author_agent="founder",
            idempotency_key="decision:001",
        )

        result = service.record_decision(decision)
        record = service.get_record(result.record_id)

        self.assertEqual(result.indexing_state, IndexingState.READY)
        self.assertEqual(record.kind, RecordKind.FOUNDER_DECISION)
        self.assertEqual(record.evidence_status, EvidenceStatus.FOUNDER_CONFIRMED)
        retry = service.record_decision(decision)
        self.assertEqual(retry.record_id, result.record_id)


class MemoryHTTPTests(unittest.TestCase):
    def test_http_api_round_trip(self) -> None:
        """Exercise the HTTP API round trip."""
        service = MemoryService(SQLiteRecordStore(":memory:"))
        server = create_server(service, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        host, port = server.server_address
        client = MemoryClient(f"http://{host}:{port}")
        try:
            self.assertEqual(client.health()["status"], "ok")
            result = client.remember(make_record("http_001"))
            self.assertEqual(result.indexing_state, IndexingState.READY)
            record = client.get_record("http_001")
            self.assertEqual(record.record_id, "http_001")
            recalled = client.recall("demo", "patient flow")
            self.assertEqual(recalled.matches[0].record.record_id, "http_001")
            with urlopen(f"http://{host}:{port}/health", timeout=5) as response:
                self.assertEqual(response.status, 200)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
