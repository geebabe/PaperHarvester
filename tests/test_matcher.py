"""Tests for title matching and similarity scoring."""

from __future__ import annotations

from paperharvester.matcher import (
    calculate_title_similarity,
    clean_text,
    evaluate_candidate_match,
    tokenize,
)
from paperharvester.models import PaperRecord


def test_clean_text():
    text = "Machine Learning: A Probabilistic Perspective (2nd ed.) — Murphy, K."
    cleaned = clean_text(text)
    assert "probabilistic" in cleaned
    assert ":" not in cleaned
    assert "(" not in cleaned
    assert "—" not in cleaned


def test_tokenize():
    tokens = tokenize("A Study on the Robustness of Deep Neural Networks")
    assert "study" in tokens
    assert "robustness" in tokens
    assert "deep" in tokens
    assert "neural" in tokens
    assert "networks" in tokens
    # Stopwords like "a", "on", "the", "of" should be removed
    assert "the" not in tokens
    assert "of" not in tokens


def test_calculate_title_similarity_identical():
    sim = calculate_title_similarity(
        "Attention Is All You Need",
        "Attention Is All You Need",
    )
    assert sim == 1.0


def test_calculate_title_similarity_minor_variations():
    t1 = "BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding"
    t2 = "BERT: Pre training of Deep Bidirectional Transformers for Language Understanding"
    sim = calculate_title_similarity(t1, t2)
    assert sim > 0.95


def test_calculate_title_similarity_subtitle_truncation():
    t1 = "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks"
    t2 = "Retrieval Augmented Generation for Knowledge Intensive Tasks"
    sim = calculate_title_similarity(t1, t2)
    assert sim > 0.85


def test_calculate_title_similarity_unrelated():
    t1 = "Attention Is All You Need"
    t2 = "Quantum Mechanics and Relativistic Quantum Field Theory"
    sim = calculate_title_similarity(t1, t2)
    assert sim < 0.20


def test_evaluate_candidate_match_doi():
    paper = PaperRecord(row_id=1, doi="10.1145/3308558.3313488")
    matched, conf, reason = evaluate_candidate_match(paper, None, candidate_doi="10.1145/3308558.3313488")
    assert matched is True
    assert conf == 1.0


def test_evaluate_candidate_match_title():
    paper = PaperRecord(row_id=1, title="Large Language Models in Legal Reasoning")
    # High similarity
    m1, c1, _ = evaluate_candidate_match(paper, "Large Language Models for Legal Reasoning")
    assert m1 is True
    assert c1 >= 0.85

    # Ambiguous similarity (overlapping terms but differing focus)
    m2, c2, r2 = evaluate_candidate_match(paper, "Large Language Models in Legal Reasoning and Statutory Statutory Interpretation")
    assert m2 is False
    assert "Ambiguous" in r2

    # Unrelated
    m3, c3, _ = evaluate_candidate_match(paper, "A Survey of Image Segmentation Using CNNs")
    assert m3 is False
    assert c3 < 0.40
