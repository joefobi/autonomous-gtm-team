"""Source loading and provenance-preserving research extraction."""

from __future__ import annotations

import hashlib
import html
import importlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Any, Mapping
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from hospital_gtm.models import EvidenceStatus, MemoryRecord, RecordKind


class ResearchError(ValueError):
    """Raised when a supplied or fetched source cannot be used."""


@dataclass(frozen=True, slots=True)
class SourceDocument:
    """Public source text with its access provenance."""

    title: str
    text: str
    accessed_at: str
    source_url: str | None = None
    source_file: str | None = None

    def __post_init__(self) -> None:
        """Validate source metadata and content."""
        for field_name in ("title", "text", "accessed_at"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ResearchError(f"{field_name} must be non-empty")
        if not self.source_url and not self.source_file:
            raise ResearchError("source_url or source_file is required")

    def excerpts(self, limit: int = 3) -> tuple[str, ...]:
        """Return short excerpts from the source text.

        Args:
            limit: Maximum number of excerpts.

        Returns:
            Non-empty sentence excerpts.
        """
        if limit < 1:
            raise ResearchError("excerpt limit must be at least one")
        sentences = re.split(r"(?<=[.!?])\s+", self.text.strip())
        excerpts = tuple(sentence.strip() for sentence in sentences if sentence.strip())
        return excerpts[:limit]

    def to_mapping(self) -> dict[str, object]:
        """Return JSON-compatible source metadata.

        Returns:
            Serialized source fields and excerpts.
        """
        return {
            "title": self.title,
            "text": self.text,
            "accessed_at": self.accessed_at,
            "source_url": self.source_url,
            "source_file": self.source_file,
            "excerpts": list(self.excerpts()),
        }


@dataclass(frozen=True, slots=True)
class ResearchFinding:
    """A sourced claim extracted from one public source."""

    hospital_id: str
    claim: str
    excerpt: str
    source: SourceDocument

    def to_record(self, author_agent: str) -> MemoryRecord:
        """Convert the finding to a canonical memory record.

        Args:
            author_agent: Agent writing the finding.

        Returns:
            Sourced memory record with provenance.
        """
        record_id = stable_record_id(self.hospital_id, self.source, "research")
        content = f"Claim: {self.claim}\nExcerpt: {self.excerpt}"
        return MemoryRecord(
            record_id=record_id,
            hospital_id=self.hospital_id,
            kind=RecordKind.PUBLIC_EVIDENCE,
            content=content,
            evidence_status=EvidenceStatus.SOURCED,
            author_agent=author_agent,
            idempotency_key=f"research:{record_id}",
            source_url=self.source.source_url,
            source_file=self.source.source_file,
            source_title=self.source.title,
            observed_at=self.source.accessed_at,
        )


def load_source(source: str | Path) -> SourceDocument:
    """Load a local source file or fetch a URL.

    Args:
        source: Local path or HTTP(S) URL.

    Returns:
        Loaded source document.
    """
    source_text = str(source)
    parsed = urlparse(source_text)
    if parsed.scheme in {"http", "https"}:
        return fetch_source(source_text)
    path = Path(source)
    if not path.is_file():
        raise ResearchError(f"source file does not exist: {path}")
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ResearchError(f"could not read source file: {path}") from exc
    if path.suffix.lower() == ".json":
        return _load_json_source(path, raw_text)
    return SourceDocument(
        title=path.stem.replace("_", " ").title(),
        text=raw_text.strip(),
        accessed_at=date.today().isoformat(),
        source_file=str(path),
    )


def fetch_source(url: str, timeout: float = 15.0) -> SourceDocument:
    """Fetch and extract a public HTML or PDF source.

    Args:
        url: HTTP(S) source URL.
        timeout: Network timeout in seconds.

    Returns:
        HTML source converted to plain text.
    """
    if urlparse(url).scheme not in {"http", "https"}:
        raise ResearchError("source URL must use http or https")
    request = Request(url, headers={"User-Agent": "hospital-gtm-research/0.1"})
    try:
        with urlopen(request, timeout=timeout) as response:
            raw_bytes = response.read()
            content_type = response.headers.get_content_type()
    except (OSError, URLError) as exc:
        raise ResearchError(f"could not fetch source URL: {url}") from exc
    if content_type == "application/pdf" or urlparse(url).path.lower().endswith(".pdf"):
        text, title = _extract_pdf(raw_bytes, url)
    else:
        raw = raw_bytes.decode("utf-8", errors="replace")
        title_match = re.search(
            r"<title[^>]*>(.*?)</title>", raw, re.IGNORECASE | re.DOTALL
        )
        title = html.unescape(title_match.group(1)).strip() if title_match else url
        body = re.sub(
            r"<script[^>]*>.*?</script>", " ", raw, flags=re.IGNORECASE | re.DOTALL
        )
        body = re.sub(
            r"<style[^>]*>.*?</style>", " ", body, flags=re.IGNORECASE | re.DOTALL
        )
        text = html.unescape(re.sub(r"<[^>]+>", " ", body))
        text = re.sub(r"\s+", " ", text).strip()
    if not text:
        raise ResearchError(f"source URL returned no readable text: {url}")
    return SourceDocument(
        title=title or url,
        text=text,
        accessed_at=date.today().isoformat(),
        source_url=url,
    )


def _extract_pdf(raw_bytes: bytes, url: str) -> tuple[str, str]:
    """Extract text and title from a PDF response.

    Args:
        raw_bytes: PDF response bytes.
        url: Source URL used as a title fallback.

    Returns:
        Extracted text and source title.
    """
    try:
        pdf_reader: Any = importlib.import_module("pypdf").PdfReader
        reader = pdf_reader(BytesIO(raw_bytes))
        text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    except Exception as exc:
        raise ResearchError(f"could not extract PDF source: {url}") from exc
    metadata_title = reader.metadata.title if reader.metadata else None
    title = metadata_title.strip() if metadata_title else url
    return text, title


def extract_findings(
    document: SourceDocument,
    hospital_id: str,
) -> tuple[ResearchFinding, ...]:
    """Extract provenance-preserving findings from a source.

    Args:
        document: Loaded source document.
        hospital_id: Hospital namespace for the findings.

    Returns:
        Extracted public-evidence findings.
    """
    if not hospital_id.strip():
        raise ResearchError("hospital_id must be non-empty")
    excerpts = document.excerpts()
    if not excerpts:
        raise ResearchError("source contains no extractable text")
    return tuple(
        ResearchFinding(
            hospital_id=hospital_id.strip(),
            claim=document.text.strip(),
            excerpt=excerpt,
            source=document,
        )
        for excerpt in excerpts[:1]
    )


def stable_record_id(
    hospital_id: str,
    source: SourceDocument,
    prefix: str,
) -> str:
    """Build a deterministic record ID for a source.

    Args:
        hospital_id: Hospital namespace.
        source: Source document.
        prefix: Record kind prefix.

    Returns:
        Stable lowercase record identifier.
    """
    identity = "|".join(
        (
            hospital_id,
            source.source_url or "",
            source.source_file or "",
            source.accessed_at,
            source.text,
        )
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


def _load_json_source(path: Path, raw_text: str) -> SourceDocument:
    """Decode a JSON source document.

    Args:
        path: JSON source path.
        raw_text: File contents.

    Returns:
        Loaded source document.
    """
    try:
        decoded: object = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ResearchError(f"source JSON is invalid: {path}") from exc
    if not isinstance(decoded, dict):
        raise ResearchError(f"source JSON must be an object: {path}")
    content = decoded.get("content")
    if not isinstance(content, str):
        raise ResearchError(f"source JSON content must be a string: {path}")
    title = decoded.get("source_title", decoded.get("title", path.stem))
    source_url = decoded.get("source_url")
    accessed_at = decoded.get("observed_at", decoded.get("accessed_at"))
    if not isinstance(title, str):
        raise ResearchError(f"source JSON title must be a string: {path}")
    if source_url is not None and not isinstance(source_url, str):
        raise ResearchError(f"source JSON source_url must be a string: {path}")
    if not isinstance(accessed_at, str) or not accessed_at.strip():
        accessed_at = date.today().isoformat()
    return SourceDocument(
        title=title,
        text=content,
        accessed_at=accessed_at,
        source_url=source_url,
        source_file=str(path),
    )
