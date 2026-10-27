"""arXiv paper resolver."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from paperharvester.models import PDFCandidate, PaperRecord
from paperharvester.resolvers.base import BaseResolver

if TYPE_CHECKING:
    import httpx

logger = logging.getLogger(__name__)


class ArxivResolver(BaseResolver):
    """Resolves papers hosted on arXiv."""

    @property
    def name(self) -> str:
        return "arXiv"

    async def can_resolve(self, paper: PaperRecord) -> bool:
        return bool(paper.normalized_arxiv_id)

    async def resolve(
        self,
        paper: PaperRecord,
        client: httpx.AsyncClient,
    ) -> list[PDFCandidate]:
        aid = paper.normalized_arxiv_id
        if not aid:
            return []

        pdf_url = f"https://arxiv.org/pdf/{aid}.pdf"
        abs_url = f"https://arxiv.org/abs/{aid}"

        return [
            PDFCandidate(
                url=pdf_url,
                source=self.name,
                confidence=1.0,
                landing_page_url=abs_url,
                matched_identifier=aid,
            )
        ]
