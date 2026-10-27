"""OpenAlex open-access resolver."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from paperharvester.matcher import evaluate_candidate_match
from paperharvester.models import PDFCandidate, PaperRecord
from paperharvester.resolvers.base import BaseResolver
from paperharvester.validators import is_safe_url

if TYPE_CHECKING:
    import httpx

logger = logging.getLogger(__name__)


class OpenAlexResolver(BaseResolver):
    """Resolves open-access PDFs using the OpenAlex Works API."""

    @property
    def name(self) -> str:
        return "OpenAlex"

    async def can_resolve(self, paper: PaperRecord) -> bool:
        return bool(paper.normalized_doi or paper.title)

    async def resolve(
        self,
        paper: PaperRecord,
        client: httpx.AsyncClient,
    ) -> list[PDFCandidate]:
        email = self.config.openalex_email or self.config.contact_email
        headers = {"User-Agent": f"PaperHarvester/1.0 (mailto:{email})"}
        params: dict[str, str] = {"mailto": email}

        work_data: dict | None = None
        match_confidence = 1.0

        # 1. Resolve by DOI first
        if paper.normalized_doi:
            doi_url = f"https://api.openalex.org/works/https://doi.org/{paper.normalized_doi}"
            try:
                resp = await client.get(doi_url, headers=headers, params=params, timeout=self.config.timeout)
                if resp.status_code == 200:
                    work_data = resp.json()
                    match_confidence = 1.0
            except Exception as exc:
                logger.debug("OpenAlex DOI lookup failed for %s: %s", paper.normalized_doi, exc)

        # 2. If no DOI or lookup failed, fallback to title search
        if not work_data and paper.title:
            search_url = "https://api.openalex.org/works"
            search_params = {
                "search": paper.title,
                "mailto": email,
                "per_page": "3",
            }
            try:
                resp = await client.get(search_url, headers=headers, params=search_params, timeout=self.config.timeout)
                if resp.status_code == 200:
                    results = resp.json().get("results", [])
                    for item in results:
                        cand_title = item.get("title")
                        cand_doi = item.get("doi")
                        matched, conf, _ = evaluate_candidate_match(paper, cand_title, cand_doi)
                        if matched:
                            work_data = item
                            match_confidence = conf
                            break
            except Exception as exc:
                logger.debug("OpenAlex title search failed for '%s': %s", paper.title, exc)

        if not work_data:
            return []

        # Extract OA locations
        best_oa = work_data.get("best_oa_location") or {}
        locations = [best_oa] + (work_data.get("oa_locations") or [])
        landing_page = work_data.get("doi") or f"https://openalex.org/{work_data.get('id', '')}"

        candidates: list[PDFCandidate] = []
        for loc in locations:
            if not loc:
                continue
            pdf_url = loc.get("pdf_url")
            if pdf_url:
                safe, _ = is_safe_url(pdf_url)
                if safe:
                    candidates.append(
                        PDFCandidate(
                            url=pdf_url,
                            source=self.name,
                            confidence=match_confidence,
                            landing_page_url=loc.get("landing_page_url") or landing_page,
                            matched_identifier=work_data.get("id", ""),
                        )
                    )
                    break

        return candidates
