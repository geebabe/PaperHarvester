"""Tests for PaperRecord, PaperResult, and normalization models."""

from __future__ import annotations

import pytest

from paperharvester.models import (
    DownloadStatus,
    FailureCategory,
    PaperRecord,
    PaperResult,
)


def test_paper_record_csv_parsing():
    row = {
        "Cite Key": "vaswani2017attention",
        "Title": "Attention Is All You Need",
        "Authors": "Ashish Vaswani and Noam Shazeer",
        "Year": "2017",
        "Publication Date": "2017-06-12",
        "Journal": "NeurIPS",
        "Volume": "30",
        "Pages": "5998-6008",
        "Abstract": "Transformers are great",
        "Citation Count": "100000",
        "Citations/Year": "14000",
        "DOI": "https://doi.org/10.48550/arXiv.1706.03762",
        "URL": "https://arxiv.org/abs/1706.03762",
        "Relevance Score": "0.99",
    }
    record = PaperRecord.from_csv_row(0, row)
    assert record.cite_key == "vaswani2017attention"
    assert record.title == "Attention Is All You Need"
    assert record.normalized_doi == "10.48550/arxiv.1706.03762"
    assert record.normalized_arxiv_id == "1706.03762"
    assert record.normalized_title == "attention is all you need"


def test_doi_normalization_edge_cases():
    test_cases = [
        ("10.1016/j.artint.2023.103980", "10.1016/j.artint.2023.103980"),
        ("https://doi.org/10.1145/3308558.3313488", "10.1145/3308558.3313488"),
        ("http://dx.doi.org/10.1007/s10506-020-09270-1.", "10.1007/s10506-020-09270-1"),
        ("doi: 10.1093/neuonc/noad054;", "10.1093/neuonc/noad054"),
        ("not a doi", None),
    ]
    for raw, expected in test_cases:
        p = PaperRecord(row_id=1, doi=raw)
        assert p.normalized_doi == expected


def test_arxiv_id_normalization():
    p1 = PaperRecord(row_id=1, url="https://arxiv.org/abs/2301.00001v2")
    assert p1.normalized_arxiv_id == "2301.00001v2"

    p2 = PaperRecord(row_id=2, url="https://arxiv.org/pdf/hep-th/9901001.pdf")
    assert p2.normalized_arxiv_id == "hep-th/9901001"

    p3 = PaperRecord(row_id=3, doi="10.48550/arXiv.2401.12345")
    assert p3.normalized_arxiv_id == "2401.12345"


def test_acl_id_normalization():
    p1 = PaperRecord(row_id=1, url="https://aclanthology.org/2020.acl-main.1/")
    assert p1.normalized_acl_id == "2020.acl-main.1"

    p2 = PaperRecord(row_id=2, url="https://aclanthology.org/P19-1001")
    assert p2.normalized_acl_id == "P19-1001"


def test_pmc_id_normalization():
    p1 = PaperRecord(row_id=1, url="https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7610000/")
    assert p1.normalized_pmc_id == "PMC7610000"


def test_filename_generation():
    p = PaperRecord(
        row_id=1,
        cite_key="vaswani2017attention",
        title="Attention Is All You Need",
        authors="Ashish Vaswani",
        year="2017",
    )
    filename = p.generate_filename()
    assert filename.startswith("vaswani2017attention")
    assert filename.endswith(".pdf")
    assert "/" not in filename
    assert "\\" not in filename
    assert ":" not in filename


def test_filename_generation_fallback_without_citekey():
    p = PaperRecord(
        row_id=5,
        title="Machine Learning for Legal Reasoning: A Survey",
        authors="Smith, John and Doe, Jane",
        year="2024",
    )
    filename = p.generate_filename()
    assert filename.startswith("smith2024")
    assert "machine_learning" in filename
    assert filename.endswith(".pdf")


def test_paper_result_dict_generation():
    raw_row = {"Cite Key": "test2024", "Title": "Test Paper", "Year": "2024"}
    res = PaperResult(
        row_id=0,
        download_status=DownloadStatus.SUCCESS,
        local_pdf_path="papers/test/pdfs/test2024.pdf",
        source_used="arXiv",
        resolved_pdf_url="https://arxiv.org/pdf/2401.12345.pdf",
        matched_identifier="2401.12345",
        match_confidence=1.0,
        file_size=123456,
        sha256="abc123hash",
        attempt_count=1,
    )
    out = res.to_results_dict(raw_row)
    assert out["Cite Key"] == "test2024"
    assert out["download_status"] == "SUCCESS"
    assert out["local_pdf_path"] == "papers/test/pdfs/test2024.pdf"
    assert out["source_used"] == "arXiv"
    assert out["sha256"] == "abc123hash"
    assert out["attempt_count"] == "1"

    failed_res = PaperResult(
        row_id=1,
        download_status=DownloadStatus.FAILED,
        failure_reason="Paywalled article",
        failure_category=FailureCategory.PAYWALLED,
        attempted_sources=["Crossref"],
        attempted_urls=["https://publishers.example.com/paper"],
        http_status=403,
        error_message="Access denied (HTTP 403)",
        suggested_manual_url="https://doi.org/10.1234/secret",
    )
    failed_out = failed_res.to_failed_dict(raw_row)
    assert failed_out["download_status"] == "FAILED"
    assert failed_out["failure_category"] == "PAYWALLED"
    assert failed_out["http_status"] == "403"
    assert failed_out["suggested_manual_url"] == "https://doi.org/10.1234/secret"
