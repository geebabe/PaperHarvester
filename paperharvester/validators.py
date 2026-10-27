"""PDF validation, content verification, and URL security checks."""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
import urllib.parse
from pathlib import Path
from typing import Set

from pypdf import PdfReader
from pypdf.errors import FileNotDecryptedError, PdfReadError

from paperharvester.matcher import clean_text, tokenize

logger = logging.getLogger(__name__)

HTML_CHALLENGE_PATTERNS = [
    re.compile(r"<!doctype\s+html", re.IGNORECASE),
    re.compile(r"<html", re.IGNORECASE),
    re.compile(r"cf-browser-verification", re.IGNORECASE),
    re.compile(r"just a moment\.\.\.", re.IGNORECASE),
    re.compile(r"access\s+denied", re.IGNORECASE),
    re.compile(r"recaptcha", re.IGNORECASE),
    re.compile(r"hcaptcha", re.IGNORECASE),
    re.compile(r"datadome", re.IGNORECASE),
    re.compile(r"<title>[^<]*(paywall|purchase|subscribe|sign\s*in|login)[^<]*</title>", re.IGNORECASE),
]

DISALLOWED_HOSTS: Set[str] = {
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "::1",
    "local",
}


def is_safe_url(url: str) -> tuple[bool, str]:
    """
    Validate URL to prevent SSRF and disallow non-web protocols.
    Returns (is_safe, error_reason).
    """
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception as exc:
        return False, f"Malformed URL: {exc}"

    if parsed.scheme.lower() not in ("http", "https"):
        return False, f"Disallowed scheme: {parsed.scheme}"

    hostname = parsed.hostname
    if not hostname:
        return False, "Missing hostname"

    host_lower = hostname.lower()
    if host_lower in DISALLOWED_HOSTS:
        return False, f"Restricted host: {hostname}"

    # Check if host is direct IP address
    try:
        ip = ipaddress.ip_address(host_lower)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
            return False, f"Restricted IP address: {ip}"
    except ValueError:
        # Not a direct IP literal; hostname will resolve through DNS during HTTP request
        pass

    return True, ""


def check_html_or_challenge(content_sample: bytes) -> tuple[bool, str]:
    """Check whether binary sample contains HTML or anti-bot/paywall challenge."""
    text_sample = content_sample[:4096].decode("utf-8", errors="ignore")
    for pattern in HTML_CHALLENGE_PATTERNS:
        if pattern.search(text_sample):
            return True, f"Detected HTML or challenge text matching '{pattern.pattern}'"
    return False, ""


def validate_pdf_file(
    file_path: Path,
    expected_title: str = "",
    min_size_bytes: int = 256,
) -> tuple[bool, str, str | None]:
    """
    Verify downloaded file is a genuine, structurally valid PDF.
    Returns (is_valid, status_description, failure_category_or_none).
    """
    if not file_path.exists():
        return False, "File does not exist on disk", "NOT_FOUND"

    file_size = file_path.stat().st_size
    if file_size < min_size_bytes:
        return False, f"File too small ({file_size} bytes, minimum {min_size_bytes})", "INVALID_PDF"

    # Read header and trailer
    try:
        with open(file_path, "rb") as f:
            header = f.read(1024)
            # Find magic bytes %PDF-
            pdf_idx = header.find(b"%PDF-")
            if pdf_idx == -1:
                is_html, html_reason = check_html_or_challenge(header)
                if is_html:
                    return False, f"File contains HTML or challenge page: {html_reason}", "PAYWALLED"
                return False, "Missing %PDF- header magic bytes", "INVALID_PDF"

            # Check for HTML content inside initial portion
            is_html, html_reason = check_html_or_challenge(header)
            if is_html:
                return False, f"File masquerading as PDF contains HTML: {html_reason}", "INVALID_PDF"

            # Read trailer
            if file_size > 2048:
                f.seek(-1024, 2)
                trailer = f.read(1024)
            else:
                f.seek(0)
                trailer = f.read()

            # Note: Many real-world PDFs end with %%EOF or trailing comments/newlines
            if b"%%EOF" not in trailer and b"EOF" not in trailer:
                logger.warning("PDF trailer %%EOF marker not found near end in %s", file_path)
    except Exception as exc:
        return False, f"Failed to read file bytes: {exc}", "INVALID_PDF"

    # Parse structure with pypdf
    try:
        reader = PdfReader(str(file_path), strict=False)
        num_pages = len(reader.pages)
        if num_pages == 0:
            return False, "PDF contains 0 pages", "INVALID_PDF"

        # Check first page
        page_0 = reader.pages[0]
        first_page_text = ""
        try:
            first_page_text = page_0.extract_text() or ""
        except Exception as e:
            logger.debug("First page text extraction note: %s", e)

        # Check metadata
        pdf_title = ""
        if reader.metadata and reader.metadata.title:
            pdf_title = str(reader.metadata.title)

        # Title verification check if expected_title is provided
        if expected_title:
            expected_tokens = tokenize(expected_title, remove_stopwords=True)
            # Check against first page text and pdf title
            combined_extracted = clean_text(f"{pdf_title} {first_page_text}")
            
            # If first page has meaningful text, check token overlap
            if len(first_page_text) > 100 and expected_tokens:
                matched_tokens = [tok for tok in expected_tokens if tok in combined_extracted]
                match_ratio = len(matched_tokens) / len(expected_tokens)
                
                # If there are at least 3 expected tokens and NONE matched, it's very likely an unrelated paper
                if len(expected_tokens) >= 3 and match_ratio == 0.0:
                    return False, f"First page does not contain expected title tokens ({expected_tokens[:3]})", "METADATA_MISMATCH"

        return True, f"Valid PDF ({num_pages} pages, {file_size} bytes)", None

    except FileNotDecryptedError:
        return False, "PDF is password protected / encrypted", "ACCESS_BLOCKED"
    except PdfReadError as err:
        return False, f"Corrupted or invalid PDF structure: {err}", "INVALID_PDF"
    except Exception as err:
        return False, f"Unexpected error parsing PDF: {err}", "INVALID_PDF"
