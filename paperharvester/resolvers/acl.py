"""ACL Anthology paper resolver."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from paperharvester.models import PDFCandidate, PaperRecord
from paperharvester.resolvers.base import BaseResolver

if TYPE_CHECKING:
    import httpx

logger = logging.getLogger(__name__)


class AclResolver(BaseResolver):
    """Resolves papers hosted on the ACL Anthology."""

    @property
    def name(self) -> str:
        return "ACL Anthology"

    async def can_resolve(self, paper: PaperRecord) -> bool:
        return bool(paper.normalized_acl_id)

    async def resolve(
        self,
        paper: PaperRecord,
        client: httpx.AsyncClient,
    ) -> list[PDFCandidate]:
        acl_id = paper.normalized_acl_id
        if not acl_id:
            return []

        pdf_url = f"https://aclanthology.org/{acl_id}.pdf"
        landing_url = f"https://aclanthology.org/{acl_id}"

        return [
            PDFCandidate(
                url=pdf_url,
                source=self.name,
                confidence=1.0,
                landing_page_url=landing_url,
                matched_identifier=acl_id,
            )
        ]
