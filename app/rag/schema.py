import re
from dataclasses import dataclass


ALLOWED_FILE_TYPES = ["pdf", "docx", "txt", "md", "doc", "rtf", "odt", "epub"]

MIN_SECTION_CHARS = 200
# Body paragraphs that start with "Part I …" must not count as headings.
MAX_HEADING_CHARS = 120

CHAPTER_HEADING_RE = re.compile(
    r"^(chapter|part|unit|module|book)\s+([0-9]+|[ivxlcdm]+)\b",
    re.IGNORECASE,
)

_NAMED_CHAPTER_KEYS = {
    "introduction": "introduction",
    "intro": "introduction",
    "conclusion": "conclusion",
    "conclusions": "conclusion",
    "abstract": "abstract",
    "preface": "preface",
    "prologue": "prologue",
    "epilogue": "epilogue",
    "summary": "summary",
    "acknowledgements": "acknowledgements",
    "acknowledgment": "acknowledgements",
    "acknowledgments": "acknowledgements",
    "references": "references",
    "bibliography": "bibliography",
    "glossary": "glossary",
    "foreword": "foreword",
    "afterword": "afterword",
    "index": "index",
    "contents": "toc",
    "toc": "toc",
}

# Multi-word named headings checked before the first-token map.
_NAMED_MULTIWORD_KEYS = {
    "table of contents": "toc",
    "list of figures": "list_of_figures",
    "list of tables": "list_of_tables",
}

_CHAPTER_KIND_RE = re.compile(
    r"^(chapter|part|unit|module|book)\s+([0-9]+|[ivxlcdm]+)\b",
    re.IGNORECASE,
)
_NUMBERED_SECTION_RE = re.compile(r"^(\d+(?:\.\d+)*)\b")
# "Chapter 1 Foo .......... 12" from a table of contents
_TOC_LEADER_RE = re.compile(r"\.{2,}\s*\d+\s*$")


def _heading_head(text: str) -> str:
    """Leading phrase of a heading before a subtitle separator."""
    return re.split(r"[:.\-—–]", (text or "").strip(), maxsplit=1)[0].strip()


def named_section_key(text: str) -> str | None:
    """Return the canonical key for a named front/back-matter heading, else None."""
    raw = (text or "").strip()
    if not raw or len(raw) > MAX_HEADING_CHARS:
        return None
    if _TOC_LEADER_RE.search(raw):
        return None
    lower_head = _heading_head(raw).lower()
    if lower_head in _NAMED_MULTIWORD_KEYS:
        return _NAMED_MULTIWORD_KEYS[lower_head]
    if lower_head in _NAMED_CHAPTER_KEYS:
        return _NAMED_CHAPTER_KEYS[lower_head]
    return None


def is_section_heading(text: str) -> bool:
    """
    True for chapter/part/unit/module/book N headings and named
    front/back-matter sections (introduction, TOC, conclusion, references, …).
    """
    raw = (text or "").strip()
    if not raw or len(raw) > MAX_HEADING_CHARS:
        return False
    if _TOC_LEADER_RE.search(raw):
        return False
    if CHAPTER_HEADING_RE.match(raw):
        return True
    return named_section_key(raw) is not None


def normalize_chapter_key(title: str) -> str:
    """
    Normalize a heading into a stable search key.

    Examples:
      "Chapter 1: Foundations" -> chapter_1
      "Introduction" -> introduction
      "Conclusion" -> conclusion
      "Table of Contents" -> toc
      "2. Methods" -> section_2
    """
    raw = (title or "").strip()
    if not raw:
        return "section"

    lower = raw.lower()

    kind_match = _CHAPTER_KIND_RE.match(lower)
    if kind_match:
        kind = kind_match.group(1).lower()
        number = kind_match.group(2).lower()
        return f"{kind}_{number}"

    named = named_section_key(raw)
    if named:
        return named

    head = _heading_head(lower)
    tokens = head.split()
    if tokens and tokens[0] == "appendix":
        suffix = "_".join(tokens[1:]) if len(tokens) > 1 else ""
        return f"appendix_{suffix}" if suffix else "appendix"

    numbered = _NUMBERED_SECTION_RE.match(lower)
    if numbered:
        return f"section_{numbered.group(1).replace('.', '_')}"

    slug = re.sub(r"[^a-z0-9]+", "_", lower).strip("_")
    return (slug[:80] or "section")


@dataclass
class SectionCandidate:
    title: str
    level: int
    start: int


@dataclass
class ExtractedSection(SectionCandidate):
    content: str
    end: int  # exclusive element index for page/image slicing


@dataclass
class ParsedSections:
    title: str
    chapter_key: str
    file_path: str
