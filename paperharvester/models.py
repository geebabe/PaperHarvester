"""Data models for PaperHarvester."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class DownloadStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    DUPLICATE = "DUPLICATE"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class FailureCategory(str, Enum):
    NOT_FOUND = "NOT_FOUND"
    PAYWALLED = "PAYWALLED"
    RATE_LIMITED = "RATE_LIMITED"
    TIMEOUT = "TIMEOUT"
    NETWORK_ERROR = "NETWORK_ERROR"
    INVALID_PDF = "INVALID_PDF"
    METADATA_MISMATCH = "METADATA_MISMATCH"
    ACCESS_BLOCKED = "ACCESS_BLOCKED"
    AMBIGUOUS_MATCH = "AMBIGUOUS_MATCH"
    UNSUPPORTED_SOURCE = "UNSUPPORTED_SOURCE"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


# Regex patterns for identifiers
DOI_PATTERN = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", re.IGNORECASE)
ARXIV_ID_PATTERN = re.compile(
    r"(?:arxiv[:\s/]|arxiv\.org/(?:abs|pdf)/)?([a-z\-]+(?:\.[a-z\-]+)?/\d{7}|\d{4}\.\d{4,5}(?:v\d+)?)",
    re.IGNORECASE,
)
ACL_ID_PATTERN = re.compile(
    r"(?:aclanthology\.org/)?([A-Z]\d{2}-\d{4}|\d{4}\.[a-z0-9\-]+\.[a-z0-9\-]+|[WDPNEC]\d{2}-\d{4})",
    re.IGNORECASE,
)
PMC_ID_PATTERN = re.compile(r"\b(PMC\d+)\b", re.IGNORECASE)


@dataclass
class PDFCandidate:
    """A potential candidate PDF URL for downloading."""
    url: str
    source: str
    confidence: float = 1.0  # 1.0 for exact identifier match, < 1.0 for heuristic or title match
    landing_page_url: str | None = None
    matched_identifier: str = ""
    extra_headers: dict[str, str] = field(default_factory=dict)


@dataclass
class PaperRecord:
    """Represents an input paper record from the CSV file."""
    row_id: int
    raw_data: dict[str, str] = field(default_factory=dict)
    cite_key: str = ""
    title: str = ""
    authors: str = ""
    year: str = ""
    publication_date: str = ""
    journal: str = ""
    volume: str = ""
    pages: str = ""
    abstract: str = ""
    citation_count: str = ""
    citations_per_year: str = ""
    doi: str = ""
    url: str = ""
    relevance_score: str = ""

    _cached_doi: str | None = field(default=None, init=False, repr=False)
    _cached_arxiv: str | None = field(default=None, init=False, repr=False)
    _cached_acl: str | None = field(default=None, init=False, repr=False)
    _cached_pmc: str | None = field(default=None, init=False, repr=False)

    @classmethod
    def from_csv_row(cls, row_id: int, row_dict: dict[str, str]) -> PaperRecord:
        """Construct PaperRecord preserving all raw fields with case-insensitive key access."""
        # Normalize key lookup
        lookup = {k.strip().lower(): v.strip() for k, v in row_dict.items() if k}

        def get_field(*aliases: str) -> str:
            for alias in aliases:
                norm = alias.lower()
                if norm in lookup:
                    return lookup[norm]
            return ""

        return cls(
            row_id=row_id,
            raw_data=dict(row_dict),
            cite_key=get_field("cite key", "citekey", "key", "id"),
            title=get_field("title", "paper title"),
            authors=get_field("authors", "author"),
            year=get_field("year"),
            publication_date=get_field("publication date", "date"),
            journal=get_field("journal", "booktitle", "venue"),
            volume=get_field("volume"),
            pages=get_field("pages"),
            abstract=get_field("abstract"),
            citation_count=get_field("citation count", "citations"),
            citations_per_year=get_field("citations/year", "citations per year"),
            doi=get_field("doi"),
            url=get_field("url", "link", "pdf url", "paper url"),
            relevance_score=get_field("relevance score", "score"),
        )

    @property
    def normalized_doi(self) -> str | None:
        """Extract and normalize DOI string (e.g., 10.1145/1234567)."""
        if self._cached_doi is not None:
            return self._cached_doi if self._cached_doi else None

        candidate = self.doi or ""
        if not candidate and self.url:
            candidate = self.url

        match = DOI_PATTERN.search(candidate)
        if match:
            doi = match.group(0).lower().rstrip(".,;)>]")
            self._cached_doi = doi
            return doi

        self._cached_doi = ""
        return None

    @property
    def normalized_arxiv_id(self) -> str | None:
        """Extract normalized arXiv ID if present in URL or DOI."""
        if self._cached_arxiv is not None:
            return self._cached_arxiv if self._cached_arxiv else None

        # Check DOI first (e.g. 10.48550/arXiv.2401.12345)
        if self.doi:
            match = ARXIV_ID_PATTERN.search(self.doi)
            if match:
                aid = match.group(1)
                self._cached_arxiv = aid
                return aid

        # Check URL
        if self.url and "arxiv.org" in self.url.lower():
            match = ARXIV_ID_PATTERN.search(self.url)
            if match:
                aid = match.group(1)
                self._cached_arxiv = aid
                return aid

        self._cached_arxiv = ""
        return None

    @property
    def normalized_acl_id(self) -> str | None:
        """Extract normalized ACL Anthology ID if present."""
        if self._cached_acl is not None:
            return self._cached_acl if self._cached_acl else None

        if self.url and "aclanthology.org" in self.url.lower():
            match = ACL_ID_PATTERN.search(self.url)
            if match:
                aid = match.group(1).rstrip("/")
                self._cached_acl = aid
                return aid

        # Check cite key or doi
        if self.cite_key:
            match = ACL_ID_PATTERN.search(self.cite_key)
            if match:
                aid = match.group(1).rstrip("/")
                self._cached_acl = aid
                return aid

        self._cached_acl = ""
        return None

    @property
    def normalized_pmc_id(self) -> str | None:
        """Extract normalized PMC ID if present."""
        if self._cached_pmc is not None:
            return self._cached_pmc if self._cached_pmc else None

        target = f"{self.url} {self.journal} {self.doi}"
        match = PMC_ID_PATTERN.search(target)
        if match:
            pmcid = match.group(1).upper()
            self._cached_pmc = pmcid
            return pmcid

        self._cached_pmc = ""
        return None

    @property
    def normalized_title(self) -> str:
        """Return a lowercased, punctuation-stripped, unicode-normalized title."""
        if not self.title:
            return ""
        # Unicode NFKD normalization
        nfkd = unicodedata.normalize("NFKD", self.title)
        # Convert to ascii ignoring diacritics
        ascii_text = nfkd.encode("ascii", "ignore").decode("ascii")
        # Lowercase and strip punctuation
        cleaned = re.sub(r"[^\w\s]", " ", ascii_text.lower())
        return re.sub(r"\s+", " ", cleaned).strip()

    def get_first_author_surname(self) -> str:
        """Extract first author surname if available."""
        if not self.authors:
            return ""
        # Authors could be "Smith, John and Doe, Jane" or "John Smith, Jane Doe"
        first = self.authors.split(";")[0].split(" and ")[0].strip()
        if "," in first:
            return first.split(",")[0].strip().lower()
        parts = first.split()
        return parts[-1].strip().lower() if parts else ""

    def generate_filename(self) -> str:
        """
        Generate a safe, descriptive, deterministic filename for the PDF.
        Uses Cite Key + sanitized short title.
        Fallback to author_year_title or DOI or hash if cite key missing.
        """
        # Build base name
        prefix = ""
        if self.cite_key:
            prefix = re.sub(r"[^\w\-]", "", self.cite_key)
        
        if not prefix:
            author = self.get_first_author_surname()
            year = re.sub(r"\D", "", self.year)[:4] if self.year else ""
            if author and year:
                prefix = f"{author}{year}"
            elif author:
                prefix = author
            elif self.normalized_doi:
                prefix = re.sub(r"[^\w\-]", "_", self.normalized_doi)
            else:
                prefix = f"paper_{self.row_id}"

        # Clean title for filename (first 4-6 meaningful words, up to 40 chars)
        clean_title = ""
        if self.title:
            norm = unicodedata.normalize("NFKD", self.title).encode("ascii", "ignore").decode("ascii")
            words = [w for w in re.sub(r"[^\w\s]", "", norm).lower().split() if len(w) > 2][:5]
            clean_title = "_".join(words)

        if clean_title:
            combined = f"{prefix}_{clean_title}"
        else:
            combined = prefix

        # Limit total length and sanitize
        safe = re.sub(r"[^\w\-]", "_", combined)[:100].strip("_")
        if not safe:
            safe = f"paper_{self.row_id}"
        return f"{safe}.pdf"


@dataclass
class PaperResult:
    """Result of attempting to harvest a paper."""
    row_id: int
    download_status: DownloadStatus
    local_pdf_path: str = ""
    source_used: str = ""
    resolved_pdf_url: str = ""
    matched_identifier: str = ""
    match_confidence: float = 0.0
    file_size: int = 0
    sha256: str = ""
    attempt_count: int = 0
    last_attempt_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    # Failure / diagnostic fields
    failure_reason: str = ""
    failure_category: FailureCategory | None = None
    attempted_sources: list[str] = field(default_factory=list)
    attempted_urls: list[str] = field(default_factory=list)
    http_status: int | None = None
    error_message: str = ""
    retry_count: int = 0
    suggested_manual_url: str = ""

    def to_results_dict(self, original_row: dict[str, str]) -> dict[str, Any]:
        """Produce dictionary containing all original CSV columns + results fields."""
        out = dict(original_row)
        out["download_status"] = self.download_status.value
        out["local_pdf_path"] = self.local_pdf_path
        out["source_used"] = self.source_used
        out["resolved_pdf_url"] = self.resolved_pdf_url
        out["matched_identifier"] = self.matched_identifier
        out["match_confidence"] = f"{self.match_confidence:.2f}"
        out["file_size"] = str(self.file_size)
        out["sha256"] = self.sha256
        out["attempt_count"] = str(self.attempt_count)
        out["last_attempt_at"] = self.last_attempt_at
        return out

    def to_failed_dict(self, original_row: dict[str, str]) -> dict[str, Any]:
        """Produce dictionary containing all original CSV columns + failure fields."""
        out = dict(original_row)
        out["download_status"] = self.download_status.value
        out["failure_reason"] = self.failure_reason
        out["failure_category"] = self.failure_category.value if self.failure_category else FailureCategory.UNKNOWN_ERROR.value
        out["attempted_sources"] = "; ".join(self.attempted_sources)
        out["attempted_urls"] = "; ".join(self.attempted_urls)
        out["http_status"] = str(self.http_status) if self.http_status is not None else ""
        out["error_message"] = self.error_message
        out["retry_count"] = str(self.retry_count)
        out["suggested_manual_url"] = self.suggested_manual_url
        return out

    def to_manifest_dict(self, original_row: dict[str, str]) -> dict[str, Any]:
        """JSON-serializable representation for manifest.jsonl."""
        res = self.to_results_dict(original_row)
        res["row_id"] = self.row_id
        res["failure_reason"] = self.failure_reason
        res["failure_category"] = self.failure_category.value if self.failure_category else None
        res["attempted_sources"] = self.attempted_sources
        res["attempted_urls"] = self.attempted_urls
        res["http_status"] = self.http_status
        res["error_message"] = self.error_message
        res["retry_count"] = self.retry_count
        res["suggested_manual_url"] = self.suggested_manual_url
        return res
