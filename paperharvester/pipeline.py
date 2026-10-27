"""Core harvesting pipeline coordinating resolution, downloads, deduplication, and persistence."""

from __future__ import annotations

import asyncio
import csv
import logging
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from paperharvester.config import Config
from paperharvester.downloader import Downloader
from paperharvester.models import (
    DownloadStatus,
    FailureCategory,
    PDFCandidate,
    PaperRecord,
    PaperResult,
)
from paperharvester.progress import ProgressReporter
from paperharvester.resolvers import get_default_resolvers
from paperharvester.resolvers.base import BaseResolver
from paperharvester.storage import StorageManager
from paperharvester.validators import validate_pdf_file

logger = logging.getLogger(__name__)


class Pipeline:
    """Coordinates reading papers, resolving sources, downloading, and storing results."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.storage = StorageManager(config)
        self.resolvers: list[BaseResolver] = get_default_resolvers(config)
        self.results: dict[int, PaperResult] = {}
        self.downloaded_papers_by_doi: dict[str, str] = {}    # doi -> local_pdf_path
        self.downloaded_papers_by_arxiv: dict[str, str] = {}  # arxiv_id -> local_pdf_path
        self.downloaded_papers_by_title: dict[str, str] = {}  # norm_title -> local_pdf_path
        self.downloaded_hashes: set[str] = set()

        self._shutdown_requested = False

    def load_input_csv(self, csv_path: Path) -> list[PaperRecord]:
        """Read CSV input preserving original columns, row order, and handling UTF-8 BOM."""
        if not csv_path.exists():
            raise FileNotFoundError(f"Input CSV file not found: {csv_path}")

        records: list[PaperRecord] = []
        with open(csv_path, "r", encoding="utf-8-sig", errors="replace") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                raise ValueError(f"CSV file {csv_path} contains no header or is empty")

            for idx, row in enumerate(reader):
                records.append(PaperRecord.from_csv_row(row_id=idx, row_dict=row))

        return records

    def _setup_signal_handlers(self) -> None:
        def handle_signal(sig, frame):
            if not self._shutdown_requested:
                self._shutdown_requested = True
                logger.warning("\nInterrupt received (Ctrl+C). Gracefully finalizing and saving state...")

        try:
            signal.signal(signal.SIGINT, handle_signal)
            signal.signal(signal.SIGTERM, handle_signal)
        except (ValueError, AttributeError):
            # Not in main thread or unsupported platform
            pass

    async def run(self) -> dict[str, Any]:
        """Execute the entire harvesting pipeline."""
        self._setup_signal_handlers()
        self.storage.setup_directories()

        # Set up logging to download.log
        file_handler = logging.FileHandler(self.storage.log_path, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s"))
        root_logger = logging.getLogger()
        root_logger.addHandler(file_handler)
        if self.config.verbose:
            root_logger.setLevel(logging.DEBUG)

        start_time_iso = datetime.now(timezone.utc).isoformat()
        start_mono = time.monotonic()

        papers = self.load_input_csv(self.config.csv_path)
        total_papers = len(papers)

        # Load previous results for resume or retry-failed
        prev_results = self.storage.load_previous_results()

        # Pre-populate deduplication index from previously validated files
        for res in prev_results.values():
            if res.download_status == DownloadStatus.SUCCESS and res.local_pdf_path:
                pdf_p = Path(res.local_pdf_path)
                if pdf_p.exists():
                    is_valid, _, _ = validate_pdf_file(pdf_p)
                    if is_valid:
                        if res.sha256:
                            self.downloaded_hashes.add(res.sha256)
                        if res.matched_identifier:
                            self.downloaded_papers_by_doi[res.matched_identifier.lower()] = res.local_pdf_path

        reporter = ProgressReporter(self.config.csv_path.name, total_papers, verbose=self.config.verbose)
        reporter.start()

        client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(self.config.timeout, connect=15.0),
        )
        downloader = Downloader(self.config, client=client)

        semaphore = asyncio.Semaphore(self.config.workers)

        async def process_paper(paper: PaperRecord) -> None:
            if self._shutdown_requested:
                return

            # Check resume / retry-failed conditions
            if paper.row_id in prev_results:
                prev = prev_results[paper.row_id]
                if self.config.retry_failed:
                    # Only re-attempt FAILED or NEEDS_REVIEW
                    if prev.download_status not in (DownloadStatus.FAILED, DownloadStatus.NEEDS_REVIEW):
                        self.results[paper.row_id] = prev
                        reporter.record_completed(
                            prev.download_status,
                            paper.cite_key or str(paper.row_id),
                            prev.source_used or "Previous",
                        )
                        return
                elif self.config.resume:
                    if prev.download_status in (DownloadStatus.SUCCESS, DownloadStatus.SKIPPED) and prev.local_pdf_path:
                        # Verify file exists and is intact
                        pdf_path = Path(prev.local_pdf_path)
                        if pdf_path.exists():
                            valid, _, _ = validate_pdf_file(pdf_path, expected_title=paper.title)
                            if valid:
                                skipped_result = PaperResult(
                                    row_id=prev.row_id,
                                    download_status=DownloadStatus.SKIPPED,
                                    local_pdf_path=prev.local_pdf_path,
                                    source_used=prev.source_used or "Resume/Cache",
                                    resolved_pdf_url=prev.resolved_pdf_url,
                                    matched_identifier=prev.matched_identifier,
                                    match_confidence=prev.match_confidence,
                                    file_size=prev.file_size,
                                    sha256=prev.sha256,
                                    attempt_count=0,
                                )
                                self.results[paper.row_id] = skipped_result
                                reporter.record_completed(
                                    DownloadStatus.SKIPPED,
                                    paper.cite_key or str(paper.row_id),
                                    "Cache/Resume",
                                )
                                return
                    elif prev.download_status == DownloadStatus.DUPLICATE:
                        self.results[paper.row_id] = prev
                        reporter.record_completed(
                            DownloadStatus.DUPLICATE,
                            paper.cite_key or str(paper.row_id),
                            "Duplicate",
                        )
                        return

            async with semaphore:
                result = await self._harvest_single_paper(paper, downloader, client)
                self.results[paper.row_id] = result
                self.storage.append_manifest_record(result, paper.raw_data)
                reporter.record_completed(
                    result.download_status,
                    paper.cite_key or paper.normalized_arxiv_id or str(paper.row_id),
                    result.source_used or "None",
                )

        try:
            tasks = [process_paper(p) for p in papers]
            await asyncio.gather(*tasks, return_exceptions=False)
        finally:
            await client.aclose()
            reporter.stop()
            root_logger.removeHandler(file_handler)
            file_handler.close()

        end_time_iso = datetime.now(timezone.utc).isoformat()
        elapsed = time.monotonic() - start_mono

        # Write reports
        self.storage.write_csv_reports(papers, self.results)
        summary = self.storage.write_summary(
            total_rows=total_papers,
            results=self.results,
            elapsed_seconds=elapsed,
            start_time=start_time_iso,
            end_time=end_time_iso,
        )

        return summary

    async def _harvest_single_paper(
        self,
        paper: PaperRecord,
        downloader: Downloader,
        client: httpx.AsyncClient,
    ) -> PaperResult:
        """Process an individual paper record through resolution, download, and validation."""
        # 1. Deduplication check against already downloaded papers in this run
        existing_path: str | None = None
        if paper.normalized_doi and paper.normalized_doi in self.downloaded_papers_by_doi:
            existing_path = self.downloaded_papers_by_doi[paper.normalized_doi]
        elif paper.normalized_arxiv_id and paper.normalized_arxiv_id in self.downloaded_papers_by_arxiv:
            existing_path = self.downloaded_papers_by_arxiv[paper.normalized_arxiv_id]
        elif paper.normalized_title and paper.normalized_title in self.downloaded_papers_by_title:
            existing_path = self.downloaded_papers_by_title[paper.normalized_title]

        if existing_path and Path(existing_path).exists():
            stat = Path(existing_path).stat()
            return PaperResult(
                row_id=paper.row_id,
                download_status=DownloadStatus.DUPLICATE,
                local_pdf_path=existing_path,
                source_used="Deduplication",
                resolved_pdf_url=paper.url or "",
                matched_identifier=paper.normalized_doi or paper.normalized_arxiv_id or "",
                match_confidence=1.0,
                file_size=stat.st_size,
                attempt_count=0,
            )

        # 2. Allocate target filename
        dest_pdf_path = self.storage.allocate_pdf_path(paper)

        # 3. Resolve candidates across all resolvers
        attempted_sources: list[str] = []
        attempted_urls: list[str] = []
        candidates: list[PDFCandidate] = []
        best_landing_url: str = paper.url or (f"https://doi.org/{paper.normalized_doi}" if paper.normalized_doi else "")

        for resolver in self.resolvers:
            if self._shutdown_requested:
                break
            try:
                can = await resolver.can_resolve(paper)
                if not can:
                    continue
                attempted_sources.append(resolver.name)
                found = await resolver.resolve(paper, client)
                if found:
                    for cand in found:
                        if cand.landing_page_url:
                            best_landing_url = cand.landing_page_url
                        candidates.append(cand)
            except Exception as exc:
                logger.debug("Resolver %s error on paper %s: %s", resolver.name, paper.row_id, exc)

        # Sort candidates by confidence descending
        candidates.sort(key=lambda c: c.confidence, reverse=True)

        if self.config.dry_run:
            if candidates:
                cand = candidates[0]
                return PaperResult(
                    row_id=paper.row_id,
                    download_status=DownloadStatus.SUCCESS,
                    local_pdf_path=str(dest_pdf_path),
                    source_used=f"[DRY RUN] {cand.source}",
                    resolved_pdf_url=cand.url,
                    matched_identifier=cand.matched_identifier,
                    match_confidence=cand.confidence,
                    suggested_manual_url=cand.landing_page_url or best_landing_url,
                )
            else:
                return PaperResult(
                    row_id=paper.row_id,
                    download_status=DownloadStatus.FAILED,
                    failure_reason="No open-access candidate found during dry run",
                    failure_category=FailureCategory.NOT_FOUND,
                    attempted_sources=attempted_sources,
                    suggested_manual_url=best_landing_url,
                )

        # 4. Attempt downloads
        last_error = ""
        last_category: FailureCategory | None = None
        last_status: int | None = None
        attempts = 0

        for cand in candidates:
            if self._shutdown_requested:
                break

            attempted_urls.append(cand.url)
            attempts += 1

            dl_res = await downloader.download_file(cand.url, dest_pdf_path, cand.extra_headers)

            if not dl_res.success:
                last_error = dl_res.error_message
                last_category = dl_res.failure_category
                last_status = dl_res.http_status
                continue

            # 5. Validate downloaded PDF
            is_valid, val_msg, val_category = validate_pdf_file(dest_pdf_path, expected_title=paper.title)

            if not is_valid:
                # Quarantine corrupt or suspicious file
                quarantine_dir = self.storage.base_dir / ".quarantine"
                quarantine_dir.mkdir(parents=True, exist_ok=True)
                quarantine_path = quarantine_dir / f"{dest_pdf_path.stem}_{int(time.time())}.pdf"
                try:
                    dest_pdf_path.replace(quarantine_path)
                except Exception:
                    pass

                last_error = f"Validation failed: {val_msg}"
                last_category = FailureCategory(val_category) if val_category and val_category in FailureCategory.__members__ else FailureCategory.INVALID_PDF
                continue

            # Check if candidate had low / ambiguous confidence
            final_status = DownloadStatus.SUCCESS
            if cand.confidence < 0.85:
                final_status = DownloadStatus.NEEDS_REVIEW

            # Register for deduplication
            if paper.normalized_doi:
                self.downloaded_papers_by_doi[paper.normalized_doi] = str(dest_pdf_path)
            if paper.normalized_arxiv_id:
                self.downloaded_papers_by_arxiv[paper.normalized_arxiv_id] = str(dest_pdf_path)
            if paper.normalized_title:
                self.downloaded_papers_by_title[paper.normalized_title] = str(dest_pdf_path)
            if dl_res.sha256:
                self.downloaded_hashes.add(dl_res.sha256)

            return PaperResult(
                row_id=paper.row_id,
                download_status=final_status,
                local_pdf_path=str(dest_pdf_path),
                source_used=cand.source,
                resolved_pdf_url=cand.url,
                matched_identifier=cand.matched_identifier,
                match_confidence=cand.confidence,
                file_size=dl_res.file_size,
                sha256=dl_res.sha256,
                attempt_count=attempts,
                suggested_manual_url=cand.landing_page_url or best_landing_url,
            )

        # If we got here, all candidates failed or no candidates were found
        failure_cat = last_category or (FailureCategory.NOT_FOUND if not candidates else FailureCategory.UNKNOWN_ERROR)
        reason = last_error or ("No open-access PDF candidate found across supported sources" if not candidates else "All candidate downloads failed")

        return PaperResult(
            row_id=paper.row_id,
            download_status=DownloadStatus.FAILED,
            failure_reason=reason,
            failure_category=failure_cat,
            attempted_sources=attempted_sources,
            attempted_urls=attempted_urls,
            http_status=last_status,
            error_message=last_error,
            attempt_count=attempts,
            suggested_manual_url=best_landing_url,
        )
