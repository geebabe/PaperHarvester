"""Open-access publisher resolvers (PLOS, Frontiers, MDPI)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from paperharvester.models import PDFCandidate, PaperRecord
from paperharvester.resolvers.base import BaseResolver

if TYPE_CHECKING:
    import httpx

logger = logging.getLogger(__name__)


class OpenPublishersResolver(BaseResolver):
    """Resolves open-access publishers like PLOS, Frontiers, and MDPI."""

    @property
    def name(self) -> str:
        return "OA Publishers"

    async def can_resolve(self, paper: PaperRecord) -> bool:
        doi = paper.normalized_doi
        url = (paper.url or "").lower()

        if doi:
            if doi.startswith("10.1371/"):  # PLOS
                return True
            if doi.startswith("10.3389/"):  # Frontiers
                return True
            if doi.startswith("10.3390/"):  # MDPI
                return True

        if "plos.org" in url or "frontiersin.org" in url or "mdpi.com" in url:
            return True

        return False

    async def resolve(
        self,
        paper: PaperRecord,
        client: httpx.AsyncClient,
    ) -> list[PDFCandidate]:
        doi = paper.normalized_doi
        url = paper.url or ""
        candidates: list[PDFCandidate] = []

        # 1. PLOS
        if (doi and doi.startswith("10.1371/")) or "plos.org" in url.lower():
            target_doi = doi or url.split("id=")[-1]
            pdf_url = f"https://journals.plos.org/plosone/article/file?id={target_doi}&type=printable"
            landing_url = f"https://journals.plos.org/plosone/article?id={target_doi}"
            candidates.append(
                PDFCandidate(
                    url=pdf_url,
                    source="PLOS",
                    confidence=1.0,
                    landing_page_url=landing_url,
                    matched_identifier=target_doi,
                )
            )

        # 2. Frontiers
        elif (doi and doi.startswith("10.3389/")) or "frontiersin.org" in url.lower():
            if doi:
                pdf_url = f"https://www.frontiersin.org/articles/{doi}/pdf"
                landing_url = f"https://doi.org/{doi}"
                candidates.append(
                    PDFCandidate(
                        url=pdf_url,
                        source="Frontiers",
                        confidence=1.0,
                        landing_page_url=landing_url,
                        matched_identifier=doi,
                    )
                )

        # 3. MDPI
        elif (doi and doi.startswith("10.3390/")) or "mdpi.com" in url.lower():
            if url and "mdpi.com" in url:
                clean_url = url.rstrip("/")
                if not clean_url.endswith("/pdf"):
                    pdf_url = f"{clean_url}/pdf"
                else:
                    pdf_url = clean_url
                candidates.append(
                    PDFCandidate(
                        url=pdf_url,
                        source="MDPI",
                        confidence=0.95,
                        landing_page_url=url,
                        matched_identifier=doi or url,
                    )
                )

        return candidates
