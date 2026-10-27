"""Live integration smoke tests against real-world open-access endpoints.

These tests make real network calls and are disabled by default.
Run explicitly with:
    pytest -m live
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from paperharvester.config import Config
from paperharvester.models import DownloadStatus
from paperharvester.pipeline import Pipeline
from paperharvester.validators import validate_pdf_file


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_arxiv_download(tmp_path: Path):
    csv_file = tmp_path / "live_test.csv"
    headers = [
        "Cite Key", "Title", "Authors", "Year", "DOI", "URL"
    ]
    # Attention Is All You Need on arXiv
    rows = [
        [
            "vaswani2017attention",
            "Attention Is All You Need",
            "Vaswani et al.",
            "2017",
            "10.48550/arXiv.1706.03762",
            "https://arxiv.org/abs/1706.03762",
        ]
    ]
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)

    config = Config(
        csv_path=csv_file,
        output_dir=tmp_path / "live_output",
        timeout=30.0,
        workers=1,
        verbose=True,
    )

    pipeline = Pipeline(config)
    summary = await pipeline.run()

    assert summary["total_rows"] == 1
    assert summary["success"] == 1

    pdfs = list((tmp_path / "live_output" / "pdfs").glob("*.pdf"))
    assert len(pdfs) == 1
    valid, _, _ = validate_pdf_file(pdfs[0], expected_title="Attention Is All You Need")
    assert valid is True
