"""Unpaywall open-access resolver."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from paperharvester.models import PDFCandidate, PaperRecord
from paperharvester.resolvers.base import BaseResolver
from paperharvester.validators import is_safe_url

if TYPE_CHECKING:
    import httpx

logger = logging.getLogger(__name__)


class UnpaywallResolver(BaseResolver):
    """Resolves open-access PDFs using the Unpaywall REST API."""

    @property
    def name(self) -> str:
        return "Unpaywall"

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

        email = self.config.unpaywall_email or self.config.contact_email
        api_url = f"https://api.unpaywall.org/v2/{doi}"

        try:
            resp = await client.get(
                api_url,
                params={"email": email},
                timeout=self.config.timeout,
            )
            if resp.status_code == 404:
                return []
            if resp.status_code != 200:
                logger.debug("Unpaywall returned status %s for DOI %s", resp.status_code, doi)
                return []

            data = resp.json()
            is_oa = data.get("is_oa", False)
            if not is_oa:
                return []

            candidates: list[PDFCandidate] = []
            best = data.get("best_oa_location") or {}
            all_locs = [best] + (data.get("oa_locations") or [])

            for loc in all_locs:
                if not loc:
                    continue
                pdf_url = loc.get("url_for_pdf")
                landing = loc.get("url_for_landing_page") or f"https://doi.org/{doi}"
                if pdf_url:
                    safe, _ = is_safe_url(pdf_url)
                    if safe:
                        candidates.append(
                            PDFCandidate(
                                url=pdf_url,
                                source=self.name,
                                confidence=1.0,
                                landing_page_url=landing,
                                matched_identifier=doi,
                            )
                        )
                        break  # Take the best valid OA location

            return candidates

        except Exception as exc:
            logger.debug("Error in Unpaywall resolution for %s: %s", doi, exc)
            return []
