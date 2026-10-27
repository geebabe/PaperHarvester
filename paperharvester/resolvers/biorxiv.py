"""bioRxiv and medRxiv preprint resolver."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from paperharvester.models import PDFCandidate, PaperRecord
from paperharvester.resolvers.base import BaseResolver

if TYPE_CHECKING:
    import httpx

logger = logging.getLogger(__name__)


class BiorxivResolver(BaseResolver):
    """Resolves preprints hosted on bioRxiv or medRxiv."""

    @property
    def name(self) -> str:
        return "bioRxiv/medRxiv"

    async def can_resolve(self, paper: PaperRecord) -> bool:
        if paper.url and ("biorxiv.org" in paper.url.lower() or "medrxiv.org" in paper.url.lower()):
            return True
        doi = paper.normalized_doi
        # Cold Spring Harbor Laboratory Press DOI prefix for bioRxiv/medRxiv is 10.1101
        return bool(doi and doi.startswith("10.1101/"))

    async def resolve(
        self,
        paper: PaperRecord,
        client: httpx.AsyncClient,
    ) -> list[PDFCandidate]:
        doi = paper.normalized_doi
        url = paper.url or ""

        # Determine domain
        domain = "medrxiv.org" if "medrxiv" in url.lower() else "biorxiv.org"
        
        candidates: list[PDFCandidate] = []
        if doi:
            pdf_url = f"https://www.{domain}/content/{doi}.full.pdf"
            landing_url = f"https://www.{domain}/content/{doi}"
            candidates.append(
                PDFCandidate(
                    url=pdf_url,
                    source=self.name,
                    confidence=1.0,
                    landing_page_url=landing_url,
                    matched_identifier=doi,
                )
            )
        elif url:
            # If URL is e.g. https://www.biorxiv.org/content/10.1101/2021.01.01.12345v1
            clean_url = url.rstrip("/")
            if not clean_url.endswith(".pdf"):
                pdf_url = f"{clean_url}.full.pdf"
            else:
                pdf_url = clean_url
            candidates.append(
                PDFCandidate(
                    url=pdf_url,
                    source=self.name,
                    confidence=0.95,
                    landing_page_url=url,
                    matched_identifier=url,
                )
            )

        return candidates
