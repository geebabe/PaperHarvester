"""Title and identity matching utilities for PaperHarvester."""

from __future__ import annotations

import difflib
import re
import unicodedata
from typing import Set

from paperharvester.models import PaperRecord

STOPWORDS: Set[str] = {
    "a", "an", "the", "and", "or", "in", "on", "at", "to", "for", "of", "with",
    "by", "from", "up", "about", "into", "over", "after", "is", "are", "was",
    "were", "be", "been", "being", "have", "has", "had", "do", "does", "did",
    "using", "via",
}


def clean_text(text: str) -> str:
    """Normalize text: strip diacritics, lowercase, strip punctuation, normalize spaces."""
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_text = nfkd.encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^\w\s]", " ", ascii_text.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def tokenize(text: str, remove_stopwords: bool = True) -> list[str]:
    """Tokenize normalized text into words."""
    words = clean_text(text).split()
    if remove_stopwords:
        return [w for w in words if w not in STOPWORDS and len(w) > 1]
    return words


def token_jaccard_similarity(tokens_a: list[str], tokens_b: list[str]) -> float:
    """Calculate Jaccard similarity between two token lists."""
    set_a = set(tokens_a)
    set_b = set(tokens_b)
    if not set_a or not set_b:
        return 0.0
    intersection = set_a.intersection(set_b)
    union = set_a.union(set_b)
    return len(intersection) / len(union)


def calculate_title_similarity(title_a: str, title_b: str) -> float:
    """
    Calculate composite similarity between two titles.
    Blends SequenceMatcher character ratio and token-level Jaccard similarity.
    Returns float in range [0.0, 1.0].
    """
    clean_a = clean_text(title_a)
    clean_b = clean_text(title_b)
    if not clean_a or not clean_b:
        return 0.0

    if clean_a == clean_b:
        return 1.0

    # Sequence matcher ratio on normalized string
    seq_ratio = difflib.SequenceMatcher(None, clean_a, clean_b).ratio()

    # Token-level jaccard on content words
    tokens_a = tokenize(clean_a, remove_stopwords=True)
    tokens_b = tokenize(clean_b, remove_stopwords=True)
    jaccard = token_jaccard_similarity(tokens_a, tokens_b)

    # If all tokens of the shorter title are contained in the longer title (e.g. subtitle truncated)
    containment = 0.0
    if tokens_a and tokens_b:
        shorter = set(tokens_a) if len(tokens_a) < len(tokens_b) else set(tokens_b)
        longer = set(tokens_b) if len(tokens_a) < len(tokens_b) else set(tokens_a)
        containment = len(shorter.intersection(longer)) / len(shorter)

    # Composite score
    composite = (0.45 * seq_ratio) + (0.35 * jaccard) + (0.20 * containment)
    return min(1.0, max(0.0, composite))


def evaluate_candidate_match(
    paper: PaperRecord,
    candidate_title: str | None,
    candidate_doi: str | None = None,
) -> tuple[bool, float, str]:
    """
    Evaluate whether a candidate corresponds to the paper.
    Returns (is_acceptable_match, confidence, reason).
    """
    # 1. Exact DOI match
    if candidate_doi and paper.normalized_doi:
        cand_norm_doi = candidate_doi.lower().strip()
        if paper.normalized_doi in cand_norm_doi or cand_norm_doi in paper.normalized_doi:
            return True, 1.0, "Exact DOI match"

    # 2. Candidate title match
    if candidate_title and paper.title:
        sim = calculate_title_similarity(paper.title, candidate_title)
        if sim >= 0.85:
            return True, sim, f"High title similarity ({sim:.2f})"
        if sim >= 0.70:
            return False, sim, f"Ambiguous title match ({sim:.2f})"
        return False, sim, f"Low title similarity ({sim:.2f})"

    # If only DOI or identifier was looked up directly without candidate metadata return 1.0
    if not candidate_title and paper.normalized_doi:
        return True, 1.0, "Identifier-based lookup"

    return False, 0.0, "Insufficient metadata to verify identity"
