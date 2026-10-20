"""Command-line entry points for the memory service and client."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from hospital_gtm.client import MemoryClient
from hospital_gtm.index import CogneeIndex, KeywordIndex, MemoryIndex
from hospital_gtm.models import DecisionRequest, MemoryRecord
from hospital_gtm.service import MemoryService, serve
from hospital_gtm.store import SQLiteRecordStore


def main(argv: Sequence[str] | None = None) -> int:
    """Run a memory CLI command.

    Args:
        argv: Optional command-line arguments.

    Returns:
        The command exit code.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)
    return int(args.handler(args))


def _build_parser() -> argparse.ArgumentParser:
    """Build the memory CLI parser.

    Returns:
        The configured argument parser.
    """
    parser = argparse.ArgumentParser(prog="memory-client")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve_parser = subparsers.add_parser("serve", help="run the local memory service")
    serve_parser.add_argument(
        "--db",
        default=os.environ.get("HOSPITAL_GTM_DATABASE", "data/memory.sqlite3"),
    )
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8765)
    serve_parser.add_argument(
        "--index", choices=("keyword", "cognee"), default="keyword"
    )
    serve_parser.add_argument("--dataset", default="hospital_gtm")
    serve_parser.set_defaults(handler=_serve)

    remember_parser = subparsers.add_parser("remember", help="store a memory record")
    remember_parser.add_argument("--url", default="http://127.0.0.1:8765")
    remember_parser.add_argument("--record-file", type=Path, required=True)
    remember_parser.set_defaults(handler=_remember)

    get_parser = subparsers.add_parser("get", help="retrieve a canonical record")
    get_parser.add_argument("record_id")
    get_parser.add_argument("--url", default="http://127.0.0.1:8765")
    get_parser.set_defaults(handler=_get)

    recall_parser = subparsers.add_parser("recall", help="recall hospital memories")
    recall_parser.add_argument("hospital_id")
    recall_parser.add_argument("query")
    recall_parser.add_argument("--url", default="http://127.0.0.1:8765")
    recall_parser.add_argument("--limit", type=int, default=20)
    recall_parser.set_defaults(handler=_recall)

    decision_parser = subparsers.add_parser(
        "decision", help="record a founder decision"
    )
    decision_parser.add_argument("--url", default="http://127.0.0.1:8765")
    decision_parser.add_argument("--decision-file", type=Path, required=True)
    decision_parser.set_defaults(handler=_decision)
    return parser


def _serve(args: argparse.Namespace) -> int:
    """Run the memory service.

    Args:
        args: Parsed service options.

    Returns:
        The service exit code.
    """
    store = SQLiteRecordStore(args.db)
    index: MemoryIndex = KeywordIndex(store)
    if args.index == "cognee":
        index = CogneeIndex(args.dataset)
    serve(MemoryService(store, index), args.host, args.port)
    return 0


def _remember(args: argparse.Namespace) -> int:
    """Send a record to the memory service.

    Args:
        args: Parsed remember options.

    Returns:
        The command exit code.
    """
    record = MemoryRecord.from_mapping(_load_object(args.record_file))
    result = MemoryClient(args.url).remember(record)
    print(json.dumps(result.to_mapping(), sort_keys=True))
    return 0


def _get(args: argparse.Namespace) -> int:
    """Fetch a canonical record.

    Args:
        args: Parsed get options.

    Returns:
        The command exit code.
    """
    record = MemoryClient(args.url).get_record(args.record_id)
    print(json.dumps(record.to_mapping(), sort_keys=True))
    return 0


def _recall(args: argparse.Namespace) -> int:
    """Recall records for a hospital.

    Args:
        args: Parsed recall options.

    Returns:
        The command exit code.
    """
    result = MemoryClient(args.url).recall(args.hospital_id, args.query, args.limit)
    print(json.dumps(result.to_mapping(), sort_keys=True))
    return 0


def _decision(args: argparse.Namespace) -> int:
    """Send a founder decision to the memory service.

    Args:
        args: Parsed decision options.

    Returns:
        The command exit code.
    """
    decision = DecisionRequest.from_mapping(_load_object(args.decision_file))
    response = MemoryClient(args.url).record_decision(decision)
    print(json.dumps(response, sort_keys=True))
    return 0


def _load_object(path: Path) -> dict[str, object]:
    """Load a JSON object from disk.

    Args:
        path: JSON file path.

    Returns:
        The decoded JSON object.
    """
    with path.open(encoding="utf-8") as file:
        value: Any = json.load(file)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
