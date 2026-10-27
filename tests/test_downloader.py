"""Tests for Downloader: streaming, atomic writes, rate limits, 429, and SSRF."""

from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import pytest
import respx

from paperharvester.config import Config
from paperharvester.downloader import Downloader
from paperharvester.models import FailureCategory


@pytest.mark.asyncio
@respx.mock
async def test_downloader_streaming_success(tmp_path: Path, test_config: Config, valid_pdf_bytes: bytes):
    url = "https://example.org/papers/attention.pdf"
    dest = tmp_path / "downloads" / "attention.pdf"

    respx.get(url).respond(
        status_code=200,
        content=valid_pdf_bytes,
        headers={"content-type": "application/pdf"},
    )

    async with httpx.AsyncClient() as client:
        downloader = Downloader(test_config, client=client)
        result = await downloader.download_file(url, dest)

        assert result.success is True
        assert result.file_path == dest
        assert dest.exists()
        assert not dest.with_suffix(".pdf.part").exists()
        assert result.file_size == len(valid_pdf_bytes)
        assert result.sha256 == hashlib.sha256(valid_pdf_bytes).hexdigest()


@pytest.mark.asyncio
@respx.mock
async def test_downloader_429_retry_after(tmp_path: Path, test_config: Config, valid_pdf_bytes: bytes):
    url = "https://example.org/papers/rate_limited.pdf"
    dest = tmp_path / "downloads" / "rate_limited.pdf"

    # First attempt: 429 with Retry-After: 0.05
    # Second attempt: 200 OK
    respx.get(url).mock(
        side_effect=[
            httpx.Response(429, headers={"retry-after": "0.05"}),
            httpx.Response(200, content=valid_pdf_bytes, headers={"content-type": "application/pdf"}),
        ]
    )

    async with httpx.AsyncClient() as client:
        downloader = Downloader(test_config, client=client)
        result = await downloader.download_file(url, dest)

        assert result.success is True
        assert result.retry_count == 1
        assert dest.exists()


@pytest.mark.asyncio
@respx.mock
async def test_downloader_403_paywall(tmp_path: Path, test_config: Config):
    url = "https://example.org/papers/paywalled.pdf"
    dest = tmp_path / "downloads" / "paywalled.pdf"

    respx.get(url).respond(status_code=403)

    async with httpx.AsyncClient() as client:
        downloader = Downloader(test_config, client=client)
        result = await downloader.download_file(url, dest)

        assert result.success is False
        assert result.failure_category == FailureCategory.PAYWALLED
        assert result.http_status == 403
        assert not dest.exists()


@pytest.mark.asyncio
@respx.mock
async def test_downloader_404_not_found(tmp_path: Path, test_config: Config):
    url = "https://example.org/papers/missing.pdf"
    dest = tmp_path / "downloads" / "missing.pdf"

    respx.get(url).respond(status_code=404)

    async with httpx.AsyncClient() as client:
        downloader = Downloader(test_config, client=client)
        result = await downloader.download_file(url, dest)

        assert result.success is False
        assert result.failure_category == FailureCategory.NOT_FOUND
        assert result.http_status == 404


@pytest.mark.asyncio
@respx.mock
async def test_downloader_html_content_type_rejection(tmp_path: Path, test_config: Config):
    url = "https://example.org/papers/paper.pdf"
    dest = tmp_path / "downloads" / "paper.pdf"

    respx.get(url).respond(
        status_code=200,
        text="<!DOCTYPE html><html><body>Access Denied</body></html>",
        headers={"content-type": "text/html; charset=utf-8"},
    )

    async with httpx.AsyncClient() as client:
        downloader = Downloader(test_config, client=client)
        result = await downloader.download_file(url, dest)

        assert result.success is False
        assert result.failure_category == FailureCategory.PAYWALLED


@pytest.mark.asyncio
async def test_downloader_ssrf_rejection(tmp_path: Path, test_config: Config):
    url = "http://127.0.0.1:8000/internal.pdf"
    dest = tmp_path / "downloads" / "internal.pdf"

    async with httpx.AsyncClient() as client:
        downloader = Downloader(test_config, client=client)
        result = await downloader.download_file(url, dest)

        assert result.success is False
        assert result.failure_category == FailureCategory.ACCESS_BLOCKED
        assert "SSRF" in result.error_message
