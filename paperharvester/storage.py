"""Persistence, directory management, and CSV/JSON reporting."""

from __future__ import annotations

import csv
import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from paperharvester.config import Config
from paperharvester.models import DownloadStatus, FailureCategory, PaperRecord, PaperResult

logger = logging.getLogger(__name__)

RESULTS_EXTRA_COLUMNS = [
    "download_status",
    "local_pdf_path",
    "source_used",
    "resolved_pdf_url",
    "matched_identifier",
    "match_confidence",
    "file_size",
    "sha256",
    "attempt_count",
    "last_attempt_at",
]

FAILED_EXTRA_COLUMNS = [
    "download_status",
    "failure_reason",
    "failure_category",
    "attempted_sources",
    "attempted_urls",
    "http_status",
    "error_message",
    "retry_count",
    "suggested_manual_url",
]


class StorageManager:
    """Manages the output directory, file naming, CSV reports, manifest, and summary."""

    def __init__(self, config: Config) -> None:
        self.config = config

        if config.output_dir:
            self.base_dir = Path(config.output_dir)
        else:
            stem = config.csv_path.stem
            self.base_dir = Path("papers") / stem

        self.pdfs_dir = self.base_dir / "pdfs"
        self.cache_dir = self.base_dir / ".cache"
        self.results_csv_path = self.base_dir / "results.csv"
        self.failed_csv_path = self.base_dir / "failed.csv"
        self.manifest_path = self.base_dir / "manifest.jsonl"
        self.summary_path = self.base_dir / "summary.json"
        self.log_path = self.base_dir / "download.log"

        # Track allocated file paths to prevent collisions between distinct papers
        self._paper_to_filename: dict[int, str] = {}
        self._used_filenames: dict[str, int] = {}  # filename -> row_id

    def setup_directories(self) -> None:
        """Create target directory hierarchy and clean stale .part files."""
        self.pdfs_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Clean stale .part files
        for part_file in self.pdfs_dir.glob("*.part"):
            try:
                part_file.unlink()
                logger.info("Cleaned up stale partial download: %s", part_file.name)
            except Exception as e:
                logger.warning("Could not delete stale part file %s: %s", part_file, e)

    def allocate_pdf_path(self, paper: PaperRecord) -> Path:
        """
        Generate a unique, safe filename for the paper.
        If a collision occurs with a different paper, disambiguate with a deterministic suffix.
        """
        if paper.row_id in self._paper_to_filename:
            return self.pdfs_dir / self._paper_to_filename[paper.row_id]

        base_name = paper.generate_filename()
        stem = Path(base_name).stem
        ext = Path(base_name).suffix

        target_name = base_name
        counter = 1

        while target_name in self._used_filenames and self._used_filenames[target_name] != paper.row_id:
            target_name = f"{stem}_{counter}{ext}"
            counter += 1

        self._used_filenames[target_name] = paper.row_id
        self._paper_to_filename[paper.row_id] = target_name
        return self.pdfs_dir / target_name

    def append_manifest_record(self, result: PaperResult, original_row: dict[str, str]) -> None:
        """Atomically append a completed paper record to manifest.jsonl."""
        record = result.to_manifest_dict(original_row)
        with open(self.manifest_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def load_previous_results(self) -> dict[int, PaperResult]:
        """
        Load previous execution state from manifest.jsonl or results.csv if present.
        Returns a mapping from row_id to PaperResult.
        """
        results: dict[int, PaperResult] = {}

        if self.manifest_path.exists():
            try:
                with open(self.manifest_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        data = json.loads(line)
                        row_id = data.get("row_id")
                        if row_id is not None:
                            status_val = data.get("download_status", "FAILED")
                            cat_val = data.get("failure_category")
                            res = PaperResult(
                                row_id=int(row_id),
                                download_status=DownloadStatus(status_val) if status_val in DownloadStatus.__members__ else DownloadStatus.FAILED,
                                local_pdf_path=data.get("local_pdf_path", ""),
                                source_used=data.get("source_used", ""),
                                resolved_pdf_url=data.get("resolved_pdf_url", ""),
                                matched_identifier=data.get("matched_identifier", ""),
                                match_confidence=float(data.get("match_confidence", 0.0)),
                                file_size=int(data.get("file_size", 0)),
                                sha256=data.get("sha256", ""),
                                attempt_count=int(data.get("attempt_count", 1)),
                                last_attempt_at=data.get("last_attempt_at", ""),
                                failure_reason=data.get("failure_reason", ""),
                                failure_category=FailureCategory(cat_val) if cat_val and cat_val in FailureCategory.__members__ else None,
                                attempted_sources=data.get("attempted_sources", []),
                                attempted_urls=data.get("attempted_urls", []),
                                http_status=data.get("http_status"),
                                error_message=data.get("error_message", ""),
                                retry_count=int(data.get("retry_count", 0)),
                                suggested_manual_url=data.get("suggested_manual_url", ""),
                            )
                            results[int(row_id)] = res
            except Exception as e:
                logger.warning("Could not read manifest.jsonl: %s", e)

        return results

    def write_csv_reports(
        self,
        papers: list[PaperRecord],
        results: dict[int, PaperResult],
    ) -> None:
        """
        Write results.csv and failed.csv preserving all original columns in order.
        """
        if not papers:
            return

        # Determine original header columns from the first paper's raw data
        first_raw = papers[0].raw_data
        original_headers = list(first_raw.keys())

        results_headers = original_headers + RESULTS_EXTRA_COLUMNS
        failed_headers = original_headers + FAILED_EXTRA_COLUMNS

        # Write results.csv
        with open(self.results_csv_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=results_headers, extrasaction="ignore")
            writer.writeheader()
            for paper in papers:
                res = results.get(paper.row_id)
                if res:
                    row_dict = res.to_results_dict(paper.raw_data)
                else:
                    # Unprocessed row
                    row_dict = dict(paper.raw_data)
                    row_dict["download_status"] = DownloadStatus.SKIPPED.value
                writer.writerow(row_dict)

        # Write failed.csv (only rows where download_status is FAILED or NEEDS_REVIEW)
        failed_papers = [
            (paper, results[paper.row_id])
            for paper in papers
            if paper.row_id in results and results[paper.row_id].download_status in (DownloadStatus.FAILED, DownloadStatus.NEEDS_REVIEW)
        ]

        with open(self.failed_csv_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=failed_headers, extrasaction="ignore")
            writer.writeheader()
            for paper, res in failed_papers:
                row_dict = res.to_failed_dict(paper.raw_data)
                writer.writerow(row_dict)

    def write_summary(
        self,
        total_rows: int,
        results: dict[int, PaperResult],
        elapsed_seconds: float,
        start_time: str,
        end_time: str,
    ) -> dict[str, Any]:
        """Generate and save summary.json."""
        success_count = sum(1 for r in results.values() if r.download_status == DownloadStatus.SUCCESS)
        failed_count = sum(1 for r in results.values() if r.download_status == DownloadStatus.FAILED)
        duplicate_count = sum(1 for r in results.values() if r.download_status == DownloadStatus.DUPLICATE)
        skipped_count = sum(1 for r in results.values() if r.download_status == DownloadStatus.SKIPPED)
        review_count = sum(1 for r in results.values() if r.download_status == DownloadStatus.NEEDS_REVIEW)

        # Source distribution
        source_dist: dict[str, int] = {}
        for r in results.values():
            if r.source_used:
                source_dist[r.source_used] = source_dist.get(r.source_used, 0) + 1

        # Failure category breakdown
        failure_dist: dict[str, int] = {}
        for r in results.values():
            if r.failure_category:
                cat_name = r.failure_category.value
                failure_dist[cat_name] = failure_dist.get(cat_name, 0) + 1

        summary_data = {
            "total_rows": total_rows,
            "success": success_count,
            "failed": failed_count,
            "duplicates": duplicate_count,
            "skipped": skipped_count,
            "needs_review": review_count,
            "unresolved": failed_count + review_count,
            "source_distribution": source_dist,
            "failure_categories": failure_dist,
            "elapsed_seconds": round(elapsed_seconds, 2),
            "start_time": start_time,
            "end_time": end_time,
        }

        with open(self.summary_path, "w", encoding="utf-8") as f:
            json.dump(summary_data, f, indent=2, ensure_ascii=False)

        return summary_data
