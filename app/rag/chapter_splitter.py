import logging
import re
import tempfile
from logging import Logger
from pathlib import Path

from unstructured.documents.elements import Element, Title

from app.rag.schema import (
    ALLOWED_FILE_TYPES,
    CHAPTER_HEADING_RE,
    MIN_SECTION_CHARS,
    ExtractedSection,
    ParsedSections,
    SectionCandidate,
    normalize_chapter_key,
)
from app.rag.unstructured_api import normalize_unstructured_base_url, partition_file_via_api
from app.utils.errors.rabbitmq import NonRetryableIngestError

class ChapterSplitter:
    def __init__(
        self,
        logger: Logger | None = None,
        unstructured_api_url: str = "http://localhost:8001",
        unstructured_api_key: str = "",
    ):
        self.logger = logger or logging.getLogger(__name__)
        self.unstructured_api_url = normalize_unstructured_base_url(unstructured_api_url)
        self.unstructured_api_key = unstructured_api_key or ""

    def initiate_chapter_split(self, filepath: str) -> list[ParsedSections]:
        """
        Split a document into chapter-level sections via the Unstructured API.
        """
        self.logger.info(f"Initiating chapter split for file: {filepath}")

        suffix = Path(filepath).suffix.lower().lstrip(".")
        if suffix not in ALLOWED_FILE_TYPES:
            raise NonRetryableIngestError(
                f"Unsupported file type: {suffix}. Should be one of: {ALLOWED_FILE_TYPES}"
            )

        elements = self._partition_file(filepath)
        if not elements:
            self.logger.warning(f"No elements found for file: {filepath}")
            return []

        self.logger.info(f"Partitioned {len(elements)} elements from file: {filepath}")

        section_candidates = self._find_chapter_candidates(elements)
        if not section_candidates:
            self.logger.warning(f"No chapter candidates found for file: {filepath}")
            return []

        self.logger.info(
            f"Found {len(section_candidates)} chapter candidates for file: {filepath}"
        )

        extracted_sections = self._extract_chapters(elements, section_candidates)
        if not extracted_sections:
            self.logger.warning(f"No extracted chapters found for file: {filepath}")
            return []

        self.logger.info(
            f"Found {len(extracted_sections)} extracted chapters for file: {filepath}"
        )

        final_parsed_documents = self._write_sections(filepath, extracted_sections)
        self.logger.info(
            f"Wrote {len(extracted_sections)} chapters to "
            f"{len(final_parsed_documents)} temp files for processing."
        )

        return final_parsed_documents

    def _partition_file(self, filepath: str) -> list[Element]:
        """Partition document into structured elements via Unstructured API."""
        try:
            self.logger.info(
                "Partitioning via Unstructured API url=%s file=%s",
                self.unstructured_api_url,
                filepath,
            )
            return partition_file_via_api(
                filepath,
                api_url=self.unstructured_api_url,
                api_key=self.unstructured_api_key,
                strategy="auto",
            )
        except Exception as e:
            self.logger.error(f"Failed to partition file {filepath}: {e}")
            raise NonRetryableIngestError(f"Failed to parse document: {e}") from e

    def _is_chapter_heading(self, text: str) -> bool:
        """True only for Chapter/Part/Unit/Module/Book N headings."""
        return bool(CHAPTER_HEADING_RE.match((text or "").strip()))

    def _find_chapter_candidates(self, elements: list[Element]) -> list[SectionCandidate]:
        """
        Find chapter headings only (ignores intro/conclusion/subsections).
        `start` is the element index used for slicing chapter bodies.
        """
        candidates: list[SectionCandidate] = []

        for index, element in enumerate(elements):
            text = str(element).strip()
            if not text:
                continue

            category = getattr(element, "category", None)
            is_title = category == "Title" or isinstance(element, Title)
            is_header = category == "Header"

            # Also accept plain narrative lines that clearly match Chapter N
            # (some parsers mis-classify headings).
            if not (is_title or is_header or self._is_chapter_heading(text)):
                continue
            if not self._is_chapter_heading(text):
                continue

            candidates.append(
                SectionCandidate(title=text, level=1, start=index)
            )

        return self._dedupe_candidates(candidates)

    def _extract_chapters(
        self, elements: list[Element], candidates: list[SectionCandidate]
    ) -> list[ExtractedSection]:
        """
        Slice element stream between consecutive chapter headings.
        Subheadings stay inside their parent chapter body.
        """
        if not candidates:
            return []

        ordered = sorted(candidates, key=lambda c: c.start)
        extracted: list[ExtractedSection] = []

        for index, candidate in enumerate(ordered):
            end = ordered[index + 1].start if index + 1 < len(ordered) else len(elements)
            if candidate.start >= end:
                continue

            parts = [
                str(elements[i]).strip()
                for i in range(candidate.start, end)
                if str(elements[i]).strip()
            ]
            content = "\n\n".join(parts).strip()
            if len(content) < MIN_SECTION_CHARS:
                self.logger.debug(
                    "Skipping short chapter title=%s chars=%s min=%s",
                    candidate.title,
                    len(content),
                    MIN_SECTION_CHARS,
                )
                continue

            extracted.append(
                ExtractedSection(
                    title=candidate.title,
                    level=candidate.level,
                    start=candidate.start,
                    content=content,
                )
            )

        return extracted

    def _write_sections(
        self, filepath: str, sections: list[ExtractedSection]
    ) -> list[ParsedSections]:
        """Write chapter bodies to temporary files for downstream processing."""
        stem = Path(filepath).stem
        out_dir = Path(tempfile.mkdtemp(prefix=f"chapters_{stem}_"))
        written: list[ParsedSections] = []
        used_keys: dict[str, int] = {}

        for index, section in enumerate(sections):
            base_key = normalize_chapter_key(section.title)
            count = used_keys.get(base_key, 0) + 1
            used_keys[base_key] = count
            chapter_key = base_key if count == 1 else f"{base_key}_{count}"

            safe_title = re.sub(r"[^\w\-]+", "_", section.title).strip("_")[:60] or "chapter"
            out_path = out_dir / f"{index:03d}_{safe_title}.txt"
            out_path.write_text(section.content, encoding="utf-8")
            written.append(
                ParsedSections(
                    title=section.title,
                    chapter_key=chapter_key,
                    file_path=str(out_path),
                )
            )
            self.logger.debug(
                "Wrote chapter title=%s chapter_key=%s path=%s chars=%s",
                section.title,
                chapter_key,
                out_path,
                len(section.content),
            )

        return written

    def _dedupe_candidates(
        self, candidates: list[SectionCandidate]
    ) -> list[SectionCandidate]:
        """Remove duplicate chapter markers at the same element index."""
        if not candidates:
            return []

        ordered = sorted(candidates, key=lambda c: (c.start, c.level))
        deduped: list[SectionCandidate] = []

        for candidate in ordered:
            if deduped and candidate.start == deduped[-1].start:
                continue
            if deduped and candidate.title.lower() == deduped[-1].title.lower():
                continue
            deduped.append(candidate)

        return deduped
