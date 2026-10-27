"""Pytest configuration and shared fixtures for PaperHarvester tests."""

from __future__ import annotations

import csv
from io import BytesIO
from pathlib import Path
from typing import Generator

import pytest
from pypdf import PdfWriter

from paperharvester.config import Config


def make_dummy_pdf_bytes(title: str = "Attention Is All You Need", author: str = "Vaswani") -> bytes:
    """Generate minimal valid PDF bytes with metadata and page structure."""
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_metadata({
        "/Title": title,
        "/Author": author,
    })
    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue()


@pytest.fixture
def valid_pdf_bytes() -> bytes:
    return make_dummy_pdf_bytes(
        title="Attention Is All You Need",
        author="Ashish Vaswani",
    )


@pytest.fixture
def html_paywall_bytes() -> bytes:
    return (
        b"<!DOCTYPE html>\n"
        b"<html>\n"
        b"<head><title>Access Denied - Purchase Article</title></head>\n"
        b"<body><h1>Subscription Required</h1><p>Please purchase access for $39.99</p></body>\n"
        b"</html>\n"
    )


@pytest.fixture
def corrupt_pdf_bytes() -> bytes:
    return b"%PDF-1.4\ncorrupted gibberish garbage not a valid pdf object"


@pytest.fixture
def test_config(tmp_path: Path) -> Config:
    from paperharvester.config import DEFAULT_DOMAIN_LIMITS, DomainRateLimit
    fast_limits = {k: DomainRateLimit(min_interval=0.001, max_concurrent=5) for k in DEFAULT_DOMAIN_LIMITS}
    return Config(
        csv_path=tmp_path / "test_papers.csv",
        output_dir=tmp_path / "output",
        workers=2,
        timeout=5.0,
        max_retries=1,
        resume=True,
        retry_failed=False,
        dry_run=False,
        verbose=True,
        domain_limits=fast_limits,
    )


@pytest.fixture
def sample_csv_path(tmp_path: Path) -> Path:
    csv_file = tmp_path / "sample_papers.csv"
    headers = [
        "Cite Key", "Title", "Authors", "Year", "Publication Date",
        "Journal", "Volume", "Pages", "Abstract", "Citation Count",
        "Citations/Year", "DOI", "URL", "Relevance Score"
    ]
    rows = [
        [
            "vaswani2017attention",
            "Attention Is All You Need",
            "Ashish Vaswani and Noam Shazeer",
            "2017",
            "2017-06-12",
            "NeurIPS",
            "30",
            "5998-6008",
            "The dominant sequence transduction models are based on complex recurrent or convolutional neural networks...",
            "100000",
            "14000",
            "10.48550/arXiv.1706.03762",
            "https://arxiv.org/abs/1706.03762",
            "0.99",
        ],
        [
            "devlin2019bert",
            "BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding",
            "Jacob Devlin and Ming-Wei Chang",
            "2019",
            "2019-06-02",
            "NAACL",
            "1",
            "4171-4186",
            "We introduce a new language representation model called BERT...",
            "80000",
            "16000",
            "10.18653/v1/N19-1423",
            "https://aclanthology.org/N19-1423/",
            "0.98",
        ],
        [
            "paywalled2024secret",
            "A Proprietary Legal Reasoning Study Behind Paywalls",
            "Alice Smith",
            "2024",
            "2024-01-01",
            "Journal of Expensive Law",
            "12",
            "1-20",
            "Secret study...",
            "10",
            "5",
            "10.9999/expensive.law.2024",
            "https://publishers.example.com/expensive-paper",
            "0.75",
        ],
        [
            "duplicate_row",
            "Attention Is All You Need",
            "Ashish Vaswani and Noam Shazeer",
            "2017",
            "2017-06-12",
            "NeurIPS",
            "30",
            "5998-6008",
            "Duplicate entry of the same paper...",
            "100000",
            "14000",
            "10.48550/arXiv.1706.03762",
            "https://arxiv.org/abs/1706.03762",
            "0.99",
        ],
    ]

    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)

    return csv_file
