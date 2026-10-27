"""Tests for PDF validation, challenge detection, and SSRF security checks."""

from __future__ import annotations

from pathlib import Path

from paperharvester.validators import (
    check_html_or_challenge,
    is_safe_url,
    validate_pdf_file,
)


def test_is_safe_url():
    # Safe public URLs
    assert is_safe_url("https://arxiv.org/pdf/2301.00001.pdf")[0] is True
    assert is_safe_url("http://aclanthology.org/2020.acl-main.1.pdf")[0] is True

    # Dangerous / SSRF URLs
    assert is_safe_url("file:///etc/passwd")[0] is False
    assert is_safe_url("ftp://example.com/paper.pdf")[0] is False
    assert is_safe_url("http://localhost:8000/private.pdf")[0] is False
    assert is_safe_url("http://127.0.0.1/admin.pdf")[0] is False
    assert is_safe_url("http://10.0.0.1/secret.pdf")[0] is False
    assert is_safe_url("http://192.168.1.100/paper.pdf")[0] is False
    assert is_safe_url("http://172.16.0.1/paper.pdf")[0] is False
    assert is_safe_url("http://0.0.0.0:80/paper.pdf")[0] is False


def test_check_html_or_challenge():
    # Genuine binary
    assert check_html_or_challenge(b"%PDF-1.4\n...")[0] is False

    # HTML
    html1 = b"<!DOCTYPE html><html><body>Access Denied</body></html>"
    assert check_html_or_challenge(html1)[0] is True

    # Cloudflare challenge
    cf_page = b"<html><head><title>Just a moment...</title></head><body>cf-browser-verification</body></html>"
    assert check_html_or_challenge(cf_page)[0] is True

    # Paywall title
    paywall = b"<html><head><title>Purchase PDF or Subscribe</title></head></html>"
    assert check_html_or_challenge(paywall)[0] is True


def test_validate_pdf_file_valid(tmp_path: Path, valid_pdf_bytes: bytes):
    pdf_path = tmp_path / "valid.pdf"
    pdf_path.write_bytes(valid_pdf_bytes)

    valid, reason, category = validate_pdf_file(pdf_path, expected_title="Attention Is All You Need")
    assert valid is True
    assert "Valid PDF" in reason
    assert category is None


def test_validate_pdf_file_nonexistent(tmp_path: Path):
    nonexistent = tmp_path / "does_not_exist.pdf"
    valid, reason, category = validate_pdf_file(nonexistent)
    assert valid is False
    assert category == "NOT_FOUND"


def test_validate_pdf_file_too_small(tmp_path: Path):
    small_file = tmp_path / "empty.pdf"
    small_file.write_bytes(b"%PDF-1.4\n")
    valid, reason, category = validate_pdf_file(small_file, min_size_bytes=500)
    assert valid is False
    assert category == "INVALID_PDF"


def test_validate_pdf_file_html_masquerading(tmp_path: Path, html_paywall_bytes: bytes):
    html_as_pdf = tmp_path / "fake.pdf"
    html_as_pdf.write_bytes(html_paywall_bytes)

    valid, reason, category = validate_pdf_file(html_as_pdf)
    assert valid is False
    assert category in ("PAYWALLED", "INVALID_PDF")


def test_validate_pdf_file_corrupt(tmp_path: Path, corrupt_pdf_bytes: bytes):
    corrupt_file = tmp_path / "corrupt.pdf"
    corrupt_file.write_bytes(corrupt_pdf_bytes + (b"\x00" * 1500))

    valid, reason, category = validate_pdf_file(corrupt_file)
    assert valid is False
    assert category == "INVALID_PDF"
