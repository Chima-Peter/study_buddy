from dataclasses import dataclass


ALLOWED_FILE_TYPES = ["pdf", "docx", "txt", "md", "html", "doc", "rtf", "odt", "htm", "epub"]


@dataclass
class SectionCandidate:
    title: str
    level: int
    start: int

@dataclass
class ExtractedSection(SectionCandidate):
    content: str

@dataclass
class FinalParsedDocument(ExtractedSection):
    file_path: str
