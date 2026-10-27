"""Crossref paper resolver."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from paperharvester.models import PDFCandidate, PaperRecord
from paperharvester.resolvers.base import BaseResolver
from paperharvester.validators import is_safe_url

if TYPE_CHECKING:
    import httpx

logger = logging.getLogger(__name__)


class CrossrefResolver(BaseResolver):
    """Resolves paper links and publisher landing pages using Crossref."""

    @property
    def name(self) -> str:
        return "Crossref"

    async def can_resolve(self, paper: PaperRecord) -> bool:
        return bool(paper.normalized_doi)

    async def resolve(
        self,
        paper: PaperRecord,
        client: httpx.AsyncClient,
    ) -> list[PDFCandidate]:
        doi = paper.normalized_doi
        if not doi:
            return []

        email = self.config.crossref_email or self.config.contact_email
        url = f"https://api.crossref.org/works/{doi}"
        headers = {"User-Agent": f"PaperHarvester/1.0 (mailto:{email})"}

        try:
            resp = await client.get(url, headers=headers, timeout=self.config.timeout)
            if resp.status_code != 200:
                return []

            data = resp.json().get("message", {})
            landing_url = data.get("resource", {}).get("primary", {}).get("URL") or data.get("URL") or f"https://doi.org/{doi}"

            candidates: list[PDFCandidate] = []
            links = data.get("link", [])
            for item in links:
                content_type = item.get("content-type", "").lower()
                pdf_url = item.get("URL")
                if "pdf" in content_type and pdf_url:
                    safe, _ = is_safe_url(pdf_url)
                    if safe:
                        candidates.append(
                            PDFCandidate(
                                url=pdf_url,
                                source=self.name,
                                confidence=1.0,
                                landing_page_url=landing_url,
                                matched_identifier=doi,
                            )
                        )
                        break

            return candidates

        except Exception as exc:
            logger.debug("Crossref lookup failed for %s: %s", doi, exc)
            return []
