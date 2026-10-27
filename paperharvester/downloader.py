"""Robust streaming HTTP downloader with rate limiting, retries, and atomic writes."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import random
import time
import urllib.parse
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx

from paperharvester.config import Config, DomainRateLimit
from paperharvester.models import FailureCategory
from paperharvester.validators import is_safe_url

logger = logging.getLogger(__name__)


@dataclass
class DownloadResult:
    """Result of an individual file download attempt."""
    success: bool
    file_path: Path | None = None
    file_size: int = 0
    sha256: str = ""
    http_status: int | None = None
    error_message: str = ""
    failure_category: FailureCategory | None = None
    retry_count: int = 0


class DomainRateLimiter:
    """Manages concurrency and minimum inter-request delays per domain."""

    def __init__(self, limits: dict[str, DomainRateLimit]) -> None:
        self.limits = limits
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._last_times: dict[str, float] = {}
        self._lock = asyncio.Lock()

    def _get_domain(self, url: str) -> str:
        try:
            parsed = urllib.parse.urlparse(url)
            return (parsed.hostname or "").lower()
        except Exception:
            return ""

    async def acquire(self, url: str) -> str:
        domain = self._get_domain(url)
        limit = self.limits.get(domain, DomainRateLimit(min_interval=0.2, max_concurrent=3))

        async with self._lock:
            if domain not in self._semaphores:
                self._semaphores[domain] = asyncio.Semaphore(limit.max_concurrent)
                self._last_times[domain] = 0.0

        sem = self._semaphores[domain]
        await sem.acquire()

        # Enforce minimum delay between calls
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_times[domain]
            if elapsed < limit.min_interval:
                delay = limit.min_interval - elapsed
                await asyncio.sleep(delay)
            self._last_times[domain] = time.monotonic()

        return domain

    def release(self, domain: str) -> None:
        if domain and domain in self._semaphores:
            self._semaphores[domain].release()


class Downloader:
    """Coordinates resilient streaming downloads."""

    def __init__(self, config: Config, client: httpx.AsyncClient | None = None) -> None:
        self.config = config
        self._external_client = client
        self.rate_limiter = DomainRateLimiter(config.domain_limits)

    def _parse_retry_after(self, header_val: str | None) -> float | None:
        if not header_val:
            return None
        val = header_val.strip()
        try:
            return float(val)
        except ValueError:
            pass
        try:
            dt = parsedate_to_datetime(val)
            delay = (dt.timestamp() - time.time())
            return max(0.0, delay)
        except Exception:
            return None

    async def download_file(
        self,
        url: str,
        dest_path: Path,
        extra_headers: dict[str, str] | None = None,
    ) -> DownloadResult:
        """
        Download a remote URL to dest_path using streaming, atomic writing,
        exponential backoff, rate limiting, and 429 Retry-After handling.
        """
        safe, reason = is_safe_url(url)
        if not safe:
            return DownloadResult(
                success=False,
                error_message=f"SSRF safety check failed: {reason}",
                failure_category=FailureCategory.ACCESS_BLOCKED,
            )

        headers = {
            "User-Agent": self.config.user_agent,
            "Accept": "application/pdf,application/octet-stream,*/*",
        }
        if extra_headers:
            headers.update(extra_headers)

        dest_path.parent.mkdir(parents=True, exist_ok=True)
        part_path = dest_path.with_suffix(dest_path.suffix + ".part")

        client = self._external_client or httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(self.config.timeout, connect=15.0),
        )
        should_close_client = self._external_client is None

        retries = 0
        backoff = 1.0

        try:
            while retries <= self.config.max_retries:
                domain = await self.rate_limiter.acquire(url)
                try:
                    async with client.stream("GET", url, headers=headers) as response:
                        status = response.status_code

                        # Successful response
                        if status == 200:
                            content_type = response.headers.get("content-type", "").lower()
                            # Check if server sent text/html with 200 OK
                            if "text/html" in content_type:
                                return DownloadResult(
                                    success=False,
                                    http_status=status,
                                    error_message="Server returned text/html instead of PDF",
                                    failure_category=FailureCategory.PAYWALLED,
                                    retry_count=retries,
                                )

                            hasher = hashlib.sha256()
                            total_bytes = 0

                            with open(part_path, "wb") as f:
                                async for chunk in response.aiter_bytes(chunk_size=65536):
                                    if chunk:
                                        f.write(chunk)
                                        hasher.update(chunk)
                                        total_bytes += len(chunk)

                            # Atomic rename
                            part_path.replace(dest_path)

                            return DownloadResult(
                                success=True,
                                file_path=dest_path,
                                file_size=total_bytes,
                                sha256=hasher.hexdigest(),
                                http_status=status,
                                retry_count=retries,
                            )

                        # Handle 429 Rate Limit
                        if status == 429:
                            retry_after = self._parse_retry_after(response.headers.get("retry-after"))
                            wait_time = retry_after if retry_after is not None else (backoff + random.uniform(0.1, 0.5))
                            logger.warning("HTTP 429 on %s, backing off %.1fs", url, wait_time)
                            retries += 1
                            if retries > self.config.max_retries:
                                return DownloadResult(
                                    success=False,
                                    http_status=429,
                                    error_message="Rate limit exceeded (HTTP 429)",
                                    failure_category=FailureCategory.RATE_LIMITED,
                                    retry_count=retries,
                                )
                            await asyncio.sleep(wait_time)
                            backoff *= 2.0
                            continue

                        # Handle 401 / 403 Forbidden / Paywall
                        if status in (401, 403):
                            return DownloadResult(
                                success=False,
                                http_status=status,
                                error_message=f"Access denied (HTTP {status})",
                                failure_category=FailureCategory.PAYWALLED,
                                retry_count=retries,
                            )

                        # Handle 404 Not Found
                        if status == 404:
                            return DownloadResult(
                                success=False,
                                http_status=404,
                                error_message="Paper not found at remote URL (HTTP 404)",
                                failure_category=FailureCategory.NOT_FOUND,
                                retry_count=retries,
                            )

                        # Handle 5xx server errors
                        if status >= 500:
                            retries += 1
                            if retries > self.config.max_retries:
                                return DownloadResult(
                                    success=False,
                                    http_status=status,
                                    error_message=f"Server error (HTTP {status})",
                                    failure_category=FailureCategory.NETWORK_ERROR,
                                    retry_count=retries,
                                )
                            jitter = random.uniform(0.1, 0.4)
                            await asyncio.sleep(backoff + jitter)
                            backoff *= 2.0
                            continue

                        # Other unhandled HTTP errors
                        return DownloadResult(
                            success=False,
                            http_status=status,
                            error_message=f"Unexpected HTTP status {status}",
                            failure_category=FailureCategory.UNKNOWN_ERROR,
                            retry_count=retries,
                        )

                except (httpx.TimeoutException, httpx.NetworkError) as net_err:
                    retries += 1
                    if retries > self.config.max_retries:
                        is_timeout = isinstance(net_err, httpx.TimeoutException)
                        return DownloadResult(
                            success=False,
                            error_message=f"Network error after {retries} retries: {net_err}",
                            failure_category=FailureCategory.TIMEOUT if is_timeout else FailureCategory.NETWORK_ERROR,
                            retry_count=retries,
                        )
                    jitter = random.uniform(0.1, 0.5)
                    await asyncio.sleep(backoff + jitter)
                    backoff *= 2.0

                finally:
                    self.rate_limiter.release(domain)

        finally:
            if should_close_client:
                await client.aclose()
            # Clean up residual .part file if failed
            if part_path.exists():
                try:
                    part_path.unlink()
                except Exception:
                    pass

        return DownloadResult(
            success=False,
            error_message="Exceeded maximum retries",
            failure_category=FailureCategory.NETWORK_ERROR,
            retry_count=retries,
        )
