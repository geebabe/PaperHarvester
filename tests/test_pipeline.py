"""End-to-end integration tests for Pipeline with mocked HTTP network calls."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import httpx
import pytest
import respx

from paperharvester.config import Config
from paperharvester.models import DownloadStatus, FailureCategory, PaperRecord
from paperharvester.pipeline import Pipeline


@pytest.mark.asyncio
@respx.mock
async def test_pipeline_end_to_end_mocked(
    sample_csv_path: Path,
    test_config: Config,
    valid_pdf_bytes: bytes,
):
    test_config.csv_path = sample_csv_path
    output_dir = test_config.output_dir
    assert output_dir is not None

    # Mock arXiv download for Attention Is All You Need
    respx.get("https://arxiv.org/pdf/1706.03762.pdf").respond(
        status_code=200,
        content=valid_pdf_bytes,
        headers={"content-type": "application/pdf"},
    )

    # Mock ACL Anthology download for BERT
    respx.get("https://aclanthology.org/N19-1423.pdf").respond(
        status_code=200,
        content=valid_pdf_bytes,
        headers={"content-type": "application/pdf"},
    )

    # Mock paywalled paper
    respx.get("https://publishers.example.com/expensive-paper").respond(
        status_code=403,
    )
    respx.get(url__startswith="https://www.ebi.ac.uk/europepmc/webservices/rest/search").respond(
        status_code=404,
    )
    respx.get(url__startswith="https://api.crossref.org/works/").respond(
        status_code=404,
    )
    respx.get(url__startswith="https://api.unpaywall.org/v2/").respond(
        status_code=404,
    )
    respx.get(url__startswith="https://api.openalex.org/works").respond(
        status_code=404,
    )
    respx.get(url__startswith="https://api.semanticscholar.org/graph/v1/paper/").respond(
        status_code=404,
    )

    pipeline = Pipeline(test_config)
    summary = await pipeline.run()

    # 1. Check summary stats
    assert summary["total_rows"] == 4
    assert summary["success"] == 2
    assert summary["failed"] == 1
    assert summary["duplicates"] == 1

    # 2. Check PDFs on disk
    pdfs_dir = output_dir / "pdfs"
    pdf_files = list(pdfs_dir.glob("*.pdf"))
    assert len(pdf_files) == 2  # Only two unique PDFs downloaded

    # 3. Check results.csv
    results_csv = output_dir / "results.csv"
    assert results_csv.exists()
    with open(results_csv, "r", encoding="utf-8-sig") as f:
        reader = list(csv.DictReader(f))
        assert len(reader) == 4
        # Original columns preserved
        assert "Cite Key" in reader[0]
        assert "Title" in reader[0]
        # Extra columns present
        assert "download_status" in reader[0]
        assert "local_pdf_path" in reader[0]
        assert "sha256" in reader[0]

        assert reader[0]["download_status"] == DownloadStatus.SUCCESS.value
        assert reader[1]["download_status"] == DownloadStatus.SUCCESS.value
        assert reader[2]["download_status"] == DownloadStatus.FAILED.value
        assert reader[3]["download_status"] == DownloadStatus.DUPLICATE.value

    # 4. Check failed.csv
    failed_csv = output_dir / "failed.csv"
    assert failed_csv.exists()
    with open(failed_csv, "r", encoding="utf-8-sig") as f:
        failed_reader = list(csv.DictReader(f))
        assert len(failed_reader) == 1
        assert failed_reader[0]["Cite Key"] == "paywalled2024secret"
        assert failed_reader[0]["download_status"] == DownloadStatus.FAILED.value
        assert failed_reader[0]["suggested_manual_url"] == "https://publishers.example.com/expensive-paper"

    # 5. Check manifest.jsonl
    manifest_file = output_dir / "manifest.jsonl"
    assert manifest_file.exists()
    with open(manifest_file, "r", encoding="utf-8") as f:
        lines = [json.loads(line) for line in f if line.strip()]
        assert len(lines) == 4

    # 6. Test resume: running pipeline again should not download existing valid PDFs
    pipeline_resume = Pipeline(test_config)
    summary_resume = await pipeline_resume.run()
    assert summary_resume["skipped"] == 2  # Already downloaded files were skipped


@pytest.mark.asyncio
async def test_pipeline_dry_run(
    sample_csv_path: Path,
    test_config: Config,
):
    test_config.csv_path = sample_csv_path
    test_config.dry_run = True
    output_dir = test_config.output_dir
    assert output_dir is not None

    pipeline = Pipeline(test_config)
    summary = await pipeline.run()

    # Dry run should resolve without saving actual PDF files to disk
    pdfs_dir = output_dir / "pdfs"
    pdf_files = list(pdfs_dir.glob("*.pdf"))
    assert len(pdf_files) == 0

    results_csv = output_dir / "results.csv"
    assert results_csv.exists()


def test_storage_collision_disambiguation(test_config: Config):
    pipeline = Pipeline(test_config)
    p1 = PaperRecord(row_id=1, cite_key="smith2024", title="Paper One")
    p2 = PaperRecord(row_id=2, cite_key="smith2024", title="Paper One")  # same base name

    path1 = pipeline.storage.allocate_pdf_path(p1)
    path2 = pipeline.storage.allocate_pdf_path(p2)

    assert path1 != path2
    assert path1.name == "smith2024_paper_one.pdf"
    assert path2.name == "smith2024_paper_one_1.pdf"
