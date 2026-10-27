"""PubMed Central (PMC) paper resolver."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from paperharvester.models import PDFCandidate, PaperRecord
from paperharvester.resolvers.base import BaseResolver

if TYPE_CHECKING:
    import httpx

logger = logging.getLogger(__name__)


class PubmedResolver(BaseResolver):
    """Resolves papers from PubMed Central / Europe PMC."""

    @property
    def name(self) -> str:
        return "PubMed Central"

    async def can_resolve(self, paper: PaperRecord) -> bool:
        if paper.normalized_pmc_id:
            return True
        if paper.url and ("ncbi.nlm.nih.gov/pmc" in paper.url.lower() or "europepmc.org" in paper.url.lower()):
            return True
        if paper.normalized_doi:
            return True
        return False

    async def resolve(
        self,
        paper: PaperRecord,
        client: httpx.AsyncClient,
    ) -> list[PDFCandidate]:
        candidates: list[PDFCandidate] = []

        pmcid = paper.normalized_pmc_id
        if pmcid:
            # Direct PMC PDF link
            pdf_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/"
            landing_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/"
            candidates.append(
                PDFCandidate(
                    url=pdf_url,
                    source=self.name,
                    confidence=1.0,
                    landing_page_url=landing_url,
                    matched_identifier=pmcid,
                )
            )
            return candidates

        # If we have a DOI, query Europe PMC API to check if OA PMC fulltext exists
        if paper.normalized_doi:
            try:
                api_url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/search"
                params = {
                    "query": f'DOI:"{paper.normalized_doi}" AND OPEN_ACCESS:y',
                    "format": "json",
                    "pageSize": "1",
                }
                resp = await client.get(api_url, params=params, timeout=self.config.timeout)
                if resp.status_code == 200:
                    data = resp.json()
                    results = data.get("resultList", {}).get("result", [])
                    if results:
                        item = results[0]
                        res_pmcid = item.get("pmcid")
                        if res_pmcid:
                            pdf_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{res_pmcid}/pdf/"
                            landing = f"https://europepmc.org/article/PMC/{res_pmcid}"
                            candidates.append(
                                PDFCandidate(
                                    url=pdf_url,
                                    source=self.name,
                                    confidence=1.0,
                                    landing_page_url=landing,
                                    matched_identifier=res_pmcid,
                                )
                            )
            except Exception as exc:
                logger.debug("Europe PMC lookup failed: %s", exc)

        return candidates
