"""Configuration settings for PaperHarvester."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class DomainRateLimit:
    """Rate limit parameters for a specific domain."""
    min_interval: float = 0.5  # Seconds between requests to this domain
    max_concurrent: int = 2     # Max concurrent requests to this domain


DEFAULT_DOMAIN_LIMITS: dict[str, DomainRateLimit] = {
    # arXiv requests no more than 1 request every 3 seconds
    "arxiv.org": DomainRateLimit(min_interval=3.0, max_concurrent=1),
    "export.arxiv.org": DomainRateLimit(min_interval=3.0, max_concurrent=1),
    # Semantic Scholar free tier: 1 req/sec without API key
    "api.semanticscholar.org": DomainRateLimit(min_interval=1.0, max_concurrent=1),
    # OpenAlex polite pool: up to 10 req/sec
    "api.openalex.org": DomainRateLimit(min_interval=0.2, max_concurrent=3),
    # Crossref polite pool
    "api.crossref.org": DomainRateLimit(min_interval=0.2, max_concurrent=2),
    # Unpaywall
    "api.unpaywall.org": DomainRateLimit(min_interval=0.2, max_concurrent=2),
    # ACL Anthology
    "aclanthology.org": DomainRateLimit(min_interval=0.5, max_concurrent=2),
    # bioRxiv / medRxiv
    "biorxiv.org": DomainRateLimit(min_interval=1.0, max_concurrent=1),
    "medrxiv.org": DomainRateLimit(min_interval=1.0, max_concurrent=1),
    # PubMed Central
    "www.ncbi.nlm.nih.gov": DomainRateLimit(min_interval=0.5, max_concurrent=2),
}


@dataclass
class Config:
    """Runtime configuration for PaperHarvester."""
    csv_path: Path = field(default_factory=lambda: Path("papers.csv"))
    output_dir: Path | None = None
    workers: int = 5
    timeout: float = 30.0
    max_retries: int = 3
    resume: bool = True
    retry_failed: bool = False
    dry_run: bool = False
    verbose: bool = False

    # Provider credentials & contact email
    contact_email: str = field(
        default_factory=lambda: (
            os.getenv("HARVESTER_EMAIL")
            or os.getenv("OPENALEX_EMAIL")
            or os.getenv("UNPAYWALL_EMAIL")
            or os.getenv("CROSSREF_EMAIL")
            or "academic-harvester@example.com"
        )
    )
    s2_api_key: str | None = field(
        default_factory=lambda: os.getenv("SEMANTIC_SCHOLAR_API_KEY") or os.getenv("S2_API_KEY")
    )
    unpaywall_email: str | None = field(
        default_factory=lambda: os.getenv("UNPAYWALL_EMAIL")
    )
    openalex_email: str | None = field(
        default_factory=lambda: os.getenv("OPENALEX_EMAIL")
    )
    crossref_email: str | None = field(
        default_factory=lambda: os.getenv("CROSSREF_EMAIL")
    )

    # User Agent
    user_agent: str = ""

    # Domain rate limits
    domain_limits: dict[str, DomainRateLimit] = field(
        default_factory=lambda: dict(DEFAULT_DOMAIN_LIMITS)
    )

    def __post_init__(self) -> None:
        if not self.user_agent:
            self.user_agent = f"PaperHarvester/1.0 (academic-downloader; mailto:{self.contact_email})"
        if not self.unpaywall_email:
            self.unpaywall_email = self.contact_email
        if not self.openalex_email:
            self.openalex_email = self.contact_email
        if not self.crossref_email:
            self.crossref_email = self.contact_email

        # If S2 API key is present, increase rate limit for Semantic Scholar
        if self.s2_api_key:
            self.domain_limits["api.semanticscholar.org"] = DomainRateLimit(min_interval=0.1, max_concurrent=5)
