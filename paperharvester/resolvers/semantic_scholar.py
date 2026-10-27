"""Semantic Scholar open-access paper resolver."""

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


class SemanticScholarResolver(BaseResolver):
    """Resolves open-access PDFs using the Semantic Scholar Academic Graph API."""

    @property
    def name(self) -> str:
        return "Semantic Scholar"

    async def can_resolve(self, paper: PaperRecord) -> bool:
        return bool(paper.normalized_doi or paper.title)

    async def resolve(
        self,
        paper: PaperRecord,
        client: httpx.AsyncClient,
    ) -> list[PDFCandidate]:
        headers: dict[str, str] = {}
        if self.config.s2_api_key:
            headers["x-api-key"] = self.config.s2_api_key

        paper_data: dict | None = None
        match_confidence = 1.0

        # 1. DOI lookup
        if paper.normalized_doi:
            url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{paper.normalized_doi}"
            params = {"fields": "title,isOpenAccess,openAccessPdf,externalIds,url"}
            try:
                resp = await client.get(url, headers=headers, params=params, timeout=self.config.timeout)
                if resp.status_code == 200:
                    paper_data = resp.json()
                    match_confidence = 1.0
            except Exception as exc:
                logger.debug("Semantic Scholar DOI lookup failed: %s", exc)

        # 2. Title search fallback
        if not paper_data and paper.title:
            url = "https://api.semanticscholar.org/graph/v1/paper/search"
            params = {
                "query": paper.title,
                "limit": "3",
                "fields": "title,isOpenAccess,openAccessPdf,externalIds,url",
            }
            try:
                resp = await client.get(url, headers=headers, params=params, timeout=self.config.timeout)
                if resp.status_code == 200:
                    data = resp.json().get("data", [])
                    for item in data:
                        cand_title = item.get("title")
                        cand_ext = item.get("externalIds") or {}
                        cand_doi = cand_ext.get("DOI")
                        matched, conf, _ = evaluate_candidate_match(paper, cand_title, cand_doi)
                        if matched:
                            paper_data = item
                            match_confidence = conf
                            break
            except Exception as exc:
                logger.debug("Semantic Scholar title search failed: %s", exc)

        if not paper_data:
            return []

        # Check for open access PDF
        oa_pdf = paper_data.get("openAccessPdf")
        if not oa_pdf:
            return []

        pdf_url = oa_pdf.get("url")
        if not pdf_url:
            return []

        safe, _ = is_safe_url(pdf_url)
        if not safe:
            return []

        landing_page = paper_data.get("url") or (f"https://doi.org/{paper.normalized_doi}" if paper.normalized_doi else None)

        return [
            PDFCandidate(
                url=pdf_url,
                source=self.name,
                confidence=match_confidence,
                landing_page_url=landing_page,
                matched_identifier=paper_data.get("paperId", ""),
            )
        ]
