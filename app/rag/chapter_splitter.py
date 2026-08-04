import logging
import re
import tempfile
from logging import Logger
from pathlib import Path

import fitz
from unstructured.documents.elements import Element, Title

from app.rag.schema import (
    ALLOWED_FILE_TYPES,
    MIN_SECTION_CHARS,
    ExtractedSection,
    ParsedSections,
    SectionCandidate,
    is_section_heading,
    named_section_key,
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
        Each section is written as a PDF so embedded images are preserved.
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

        final_parsed_documents = self._write_sections(
            filepath, elements, extracted_sections
        )
        self.logger.info(
            f"Wrote {len(extracted_sections)} chapters to "
            f"{len(final_parsed_documents)} temp PDF files for processing."
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

    def _is_section_heading(self, text: str) -> bool:
        """True for numbered chapter-like headings and named front/back matter."""
        return is_section_heading(text)

    def _find_chapter_candidates(self, elements: list[Element]) -> list[SectionCandidate]:
        """
        Find top-level section headings (chapters plus intro/TOC/conclusion/etc.).
        Subsections like "1.1 …" are left inside their parent body.
        `start` is the element index used for slicing section bodies.
        """
        candidates: list[SectionCandidate] = []

        for index, element in enumerate(elements):
            text = str(element).strip()
            if not text:
                continue

            category = getattr(element, "category", None)
            is_title = category == "Title" or isinstance(element, Title)
            is_header = category == "Header"

            # Also accept plain narrative lines that clearly match a section
            # heading (some parsers mis-classify headings).
            if not (is_title or is_header or self._is_section_heading(text)):
                continue
            if not self._is_section_heading(text):
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
            if len(content) < MIN_SECTION_CHARS and named_section_key(candidate.title) is None:
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
                    end=end,
                    content=content,
                )
            )

        return extracted

    def _write_sections(
        self,
        filepath: str,
        elements: list[Element],
        sections: list[ExtractedSection],
    ) -> list[ParsedSections]:
        """Write each chapter as a PDF (page-sliced when source is PDF)."""
        stem = Path(filepath).stem
        out_dir = Path(tempfile.mkdtemp(prefix=f"chapters_{stem}_"))
        written: list[ParsedSections] = []
        used_keys: dict[str, int] = {}
        source_is_pdf = Path(filepath).suffix.lower() == ".pdf"
        source_doc = fitz.open(filepath) if source_is_pdf else None

        try:
            for index, section in enumerate(sections):
                base_key = normalize_chapter_key(section.title)
                count = used_keys.get(base_key, 0) + 1
                used_keys[base_key] = count
                chapter_key = base_key if count == 1 else f"{base_key}_{count}"

                safe_title = (
                    re.sub(r"[^\w\-]+", "_", section.title).strip("_")[:60] or "chapter"
                )
                out_path = out_dir / f"{index:03d}_{safe_title}.pdf"

                if source_doc is not None:
                    self._write_pdf_page_slice(
                        source_doc, elements, section, out_path
                    )
                else:
                    self._write_text_pdf(section.title, section.content, out_path)

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
        finally:
            if source_doc is not None:
                source_doc.close()

        return written

    def _element_page(self, element: Element) -> int | None:
        """1-based page number from Unstructured metadata, if present."""
        meta = getattr(element, "metadata", None)
        page = getattr(meta, "page_number", None) if meta else None
        if page is None:
            return None
        try:
            return int(page)
        except (TypeError, ValueError):
            return None

    def _write_pdf_page_slice(
        self,
        source_doc: fitz.Document,
        elements: list[Element],
        section: ExtractedSection,
        out_path: Path,
    ) -> None:
        """Copy source pages spanning this section so images stay embedded."""
        pages: list[int] = []
        for i in range(section.start, section.end):
            page = self._element_page(elements[i])
            if page is not None:
                pages.append(page)

        out = fitz.open()
        try:
            if pages:
                # Unstructured pages are 1-based; fitz is 0-based.
                start_page = max(0, min(pages) - 1)
                end_page = min(source_doc.page_count - 1, max(pages) - 1)
                out.insert_pdf(source_doc, from_page=start_page, to_page=end_page)
            else:
                # No page metadata — fall back to a text-only PDF.
                self._append_text_pages(out, section.title, section.content)
            out.save(out_path)
        finally:
            out.close()

    def _write_text_pdf(self, title: str, content: str, out_path: Path) -> None:
        """Render non-PDF chapter content into a simple text PDF."""
        out = fitz.open()
        try:
            self._append_text_pages(out, title, content)
            out.save(out_path)
        finally:
            out.close()

    def _append_text_pages(self, doc: fitz.Document, title: str, content: str) -> None:
        width, height = fitz.paper_size("a4")
        margin = 54
        line_height = 14
        page = doc.new_page(width=width, height=height)
        y = margin
        page.insert_text((margin, y), title[:200], fontsize=16, fontname="helv")
        y += 28
        for raw_line in (content or "").splitlines() or [""]:
            # Soft-wrap long lines for the text fallback path.
            chunk = raw_line if raw_line else " "
            while chunk:
                piece, chunk = chunk[:100], chunk[100:]
                if y > height - margin:
                    page = doc.new_page(width=width, height=height)
                    y = margin
                page.insert_text((margin, y), piece, fontsize=11, fontname="helv")
                y += line_height

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
