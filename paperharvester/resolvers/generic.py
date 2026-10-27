"""Generic landing page resolver extracting PDF links from HTML metadata."""

from __future__ import annotations

import logging
import re
import urllib.parse
from typing import TYPE_CHECKING

from paperharvester.models import PDFCandidate, PaperRecord
from paperharvester.resolvers.base import BaseResolver
from paperharvester.validators import is_safe_url

if TYPE_CHECKING:
    import httpx

logger = logging.getLogger(__name__)

META_PDF_PATTERNS = [
    re.compile(r'<meta\s+name=["\']citation_pdf_url["\']\s+content=["\']([^"\']+)["\']', re.IGNORECASE),
    re.compile(r'<meta\s+content=["\']([^"\']+)["\']\s+name=["\']citation_pdf_url["\']', re.IGNORECASE),
    re.compile(r'<meta\s+name=["\']eprints\.document_url["\']\s+content=["\']([^"\']+)["\']', re.IGNORECASE),
    re.compile(r'<meta\s+name=["\']bpc:pdf_url["\']\s+content=["\']([^"\']+)["\']', re.IGNORECASE),
]

PAYWALL_TEXT_PATTERNS = [
    re.compile(r"purchase\s+pdf", re.IGNORECASE),
    re.compile(r"buy\s+article", re.IGNORECASE),
    re.compile(r"subscribe\s+to\s+journal", re.IGNORECASE),
    re.compile(r"access\s+through\s+your\s+institution", re.IGNORECASE),
    re.compile(r"institutional\s+login", re.IGNORECASE),
    re.compile(r"rent\s+this\s+article", re.IGNORECASE),
]


class GenericResolver(BaseResolver):
    """Inspects generic HTML landing pages for PDF meta tags and open-access links."""

    @property
    def name(self) -> str:
        return "Generic Landing Page"

    async def can_resolve(self, paper: PaperRecord) -> bool:
        if paper.url:
            safe, _ = is_safe_url(paper.url)
            return safe
        if paper.normalized_doi:
            return True
        return False

    async def resolve(
        self,
        paper: PaperRecord,
        client: httpx.AsyncClient,
    ) -> list[PDFCandidate]:
        target_url = paper.url
        if not target_url and paper.normalized_doi:
            target_url = f"https://doi.org/{paper.normalized_doi}"

        if not target_url:
            return []

        safe, _ = is_safe_url(target_url)
        if not safe:
            return []

        try:
            resp = await client.get(
                target_url,
                follow_redirects=True,
                timeout=self.config.timeout,
            )
            # If server returned paywall or blocked
            if resp.status_code in (401, 403):
                return []
            if resp.status_code != 200:
                return []

            content_type = resp.headers.get("content-type", "").lower()
            # If redirected straight to a PDF
            if "application/pdf" in content_type:
                return [
                    PDFCandidate(
                        url=str(resp.url),
                        source="Direct Redirect",
                        confidence=0.95,
                        landing_page_url=target_url,
                        matched_identifier=paper.normalized_doi or target_url,
                    )
                ]

            html_text = resp.text
            final_url = str(resp.url)

            # Check meta tags
            for pattern in META_PDF_PATTERNS:
                match = pattern.search(html_text)
                if match:
                    pdf_link = match.group(1).strip()
                    # Resolve relative URL
                    full_pdf_url = urllib.parse.urljoin(final_url, pdf_link)
                    safe_pdf, _ = is_safe_url(full_pdf_url)
                    if safe_pdf:
                        return [
                            PDFCandidate(
                                url=full_pdf_url,
                                source="Landing Page Meta",
                                confidence=0.90,
                                landing_page_url=final_url,
                                matched_identifier=paper.normalized_doi or target_url,
                            )
                        ]

            # Look for direct anchor links with PDF
            # e.g., <a ... href="...pdf" ...>Download PDF</a>
            anchor_match = re.search(
                r'<a[^>]+href=["\']([^"\']+\.pdf(?:\?[^"\']*)?)["\'][^>]*>(?:[^<]*(?:pdf|download|full\s*text)[^<]*)</a>',
                html_text,
                re.IGNORECASE,
            )
            if anchor_match:
                pdf_link = anchor_match.group(1).strip()
                full_pdf_url = urllib.parse.urljoin(final_url, pdf_link)
                safe_pdf, _ = is_safe_url(full_pdf_url)
                if safe_pdf:
                    return [
                        PDFCandidate(
                            url=full_pdf_url,
                            source="Landing Page Link",
                            confidence=0.85,
                            landing_page_url=final_url,
                            matched_identifier=paper.normalized_doi or target_url,
                        )
                    ]

            return []

        except Exception as exc:
            logger.debug("Generic landing page resolution failed for %s: %s", target_url, exc)
            return []
