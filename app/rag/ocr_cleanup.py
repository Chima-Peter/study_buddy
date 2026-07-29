"""
OCR cleanup utilities for image-based document ingestion.

Uses Unstructured's built-in cleaners plus lightweight post-processing
to remove OCR artifacts while preserving document structure.
"""

import re
from collections import Counter

from langchain_core.documents import Document
from unstructured.cleaners.core import (
    clean_extra_whitespace,
    replace_unicode_quotes,
)

# Short garbage patterns common in OCR output (for whole-line filtering)
_GARBAGE_LINE_PATTERN = re.compile(
    r"^[\s\W]{0,3}$"  # 0-3 chars of whitespace/punctuation only
    r"|^[a-zA-Z]{1,2}$"  # single/double letter fragments
    r"|^\d{1,2}$"  # lone 1-2 digit numbers (often page artifacts)
    r"|^[~|\\/_\-]{1,5}$"  # short runs of symbols
)

# Common OCR noise tokens to strip (inline and line-level)
_NOISE_TOKENS = frozenset({
    "ou", "fWN", "~N", "oO", "lI", "Il", "Oo", "rn", "vv",
    "; ou fWN", "ou fWN", "~N", "; ~N",
})

# Inline noise: only whole tokens (word-bounded), never substring matches
# Catches: "; ou fWN", standalone "~N" / "fWN", etc.
_INLINE_NOISE_PATTERN = re.compile(
    r"(?:^|\s|;)\s*"
    r"(?:ou|fWN|~N|oO|lI|Il|Oo|rn|vv)"
    r"(?:\s+(?:ou|fWN|~N|oO|lI|Il|Oo|rn|vv))*"
    r"(?=\s|;|$)",
)


def _is_garbage_line(text: str) -> bool:
    """Check if a line is likely OCR garbage."""
    stripped = text.strip()
    if not stripped:
        return True
    if stripped in _NOISE_TOKENS:
        return True
    if _GARBAGE_LINE_PATTERN.match(stripped):
        return True
    return False


def _remove_inline_noise(text: str) -> str:
    """Remove common inline OCR noise tokens."""
    text = _INLINE_NOISE_PATTERN.sub(" ", text)
    return text


def _normalize_whitespace(text: str) -> str:
    """Normalize whitespace using Unstructured's cleaner."""
    text = replace_unicode_quotes(text)
    text = _remove_inline_noise(text)
    text = clean_extra_whitespace(text)
    return text


def _detect_repeated_headers_footers(
    documents: list[Document],
    min_occurrences: int = 2,
    max_length: int = 120,
) -> set[str]:
    """
    Detect text that appears in multiple documents unchanged.
    Likely page headers/footers if short and repeated.
    """
    if len(documents) < min_occurrences:
        return set()

    candidates: Counter[str] = Counter()
    for doc in documents:
        lines = doc.page_content.strip().split("\n")
        for line in lines[:3] + lines[-3:]:
            cleaned = line.strip()
            if cleaned and len(cleaned) <= max_length:
                candidates[cleaned] += 1

    return {
        text for text, count in candidates.items()
        if count >= min_occurrences
    }


def _remove_repeated_lines(text: str, repeated: set[str]) -> str:
    """Remove lines that match repeated header/footer patterns."""
    if not repeated:
        return text
    lines = text.split("\n")
    filtered = [line for line in lines if line.strip() not in repeated]
    return "\n".join(filtered)


def clean_ocr_documents(
    documents: list[Document],
    remove_headers_footers: bool = True,
    remove_garbage: bool = True,
    normalize_ws: bool = True,
) -> list[Document]:
    """
    Clean OCR output while preserving structure.

    - Normalizes whitespace (collapses runs, fixes unicode)
    - Removes repeated page headers/footers across chunks
    - Removes short garbage tokens from OCR noise
    - Preserves Table and other structured element types
    """
    if not documents:
        return documents

    repeated = set()
    if remove_headers_footers:
        repeated = _detect_repeated_headers_footers(documents)

    cleaned: list[Document] = []
    for doc in documents:
        text = doc.page_content

        if normalize_ws:
            text = _normalize_whitespace(text)

        if remove_headers_footers and repeated:
            text = _remove_repeated_lines(text, repeated)

        if remove_garbage:
            lines = text.split("\n")
            lines = [line for line in lines if not _is_garbage_line(line)]
            text = "\n".join(lines)

        text = text.strip()
        if not text:
            continue

        cleaned.append(
            Document(page_content=text, metadata=doc.metadata.copy())
        )

    return cleaned
