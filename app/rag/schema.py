import re
from dataclasses import dataclass


ALLOWED_FILE_TYPES = ["pdf", "docx", "txt", "md", "html", "doc", "rtf", "odt", "htm", "epub"]

MIN_SECTION_CHARS = 200

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
}

_CHAPTER_KIND_RE = re.compile(
    r"^(chapter|part|unit|module|book)\s+([0-9]+|[ivxlcdm]+)\b",
    re.IGNORECASE,
)
_NUMBERED_SECTION_RE = re.compile(r"^(\d+(?:\.\d+)*)\b")


def normalize_chapter_key(title: str) -> str:
    """
    Normalize a heading into a stable search key.

    Examples:
      "Chapter 1: Foundations" -> chapter_1
      "Introduction" -> introduction
      "Conclusion" -> conclusion
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

    head = re.split(r"[:.\-—–]", lower, maxsplit=1)[0].strip()
    tokens = head.split()
    if tokens:
        first = tokens[0]
        if first in _NAMED_CHAPTER_KEYS:
            return _NAMED_CHAPTER_KEYS[first]
        if first == "appendix":
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


@dataclass
class ParsedSections:
    title: str
    chapter_key: str
    file_path: str
