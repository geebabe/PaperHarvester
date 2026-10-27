"""Direct PDF URL resolver."""

from __future__ import annotations

import urllib.parse
from typing import TYPE_CHECKING

from paperharvester.models import PDFCandidate, PaperRecord
from paperharvester.resolvers.base import BaseResolver
from paperharvester.validators import is_safe_url

if TYPE_CHECKING:
    import httpx


class DirectResolver(BaseResolver):
    """Resolves papers whose URL already points directly to a PDF file."""

    @property
    def name(self) -> str:
        return "Direct PDF"

    async def can_resolve(self, paper: PaperRecord) -> bool:
        if not paper.url:
            return False
        safe, _ = is_safe_url(paper.url)
        if not safe:
            return False
        
        parsed = urllib.parse.urlparse(paper.url)
        path_lower = parsed.path.lower()
        query_lower = parsed.query.lower()
        return path_lower.endswith(".pdf") or "type=printable" in query_lower or "format=pdf" in query_lower

    async def resolve(
        self,
        paper: PaperRecord,
        client: httpx.AsyncClient,
    ) -> list[PDFCandidate]:
        if not paper.url:
            return []
        return [
            PDFCandidate(
                url=paper.url,
                source=self.name,
                confidence=1.0,
                landing_page_url=paper.url,
                matched_identifier=paper.url,
            )
        ]
