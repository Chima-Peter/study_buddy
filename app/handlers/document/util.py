import asyncio
import shutil
from logging import Logger
from pathlib import Path

from langchain_core.documents import Document

from app.core.redis import RedisClient
from app.rag.chapter_splitter import ChapterSplitter
from app.rag.ingest_pipeline import IngestPipeline
from app.rag.schema import ParsedSections
from app.system.schemas.document import ALL_ALLOWED_EXTENSIONS, DocumentResponse, IngestDocumentRequest
from app.system.schemas.notification import CreateNotificationRequest, EventPayload
from app.system.service.document import DocumentService
from app.system.service.notification import NotificationService

_ALLOWED_EXT_HELP = ", ".join(sorted(ALL_ALLOWED_EXTENSIONS))


def is_file_not_found_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    status_code = getattr(exc, "response", None)
    code = getattr(status_code, "status_code", None) if status_code is not None else None
    if code == 404:
        return True
    if getattr(exc, "status_code", None) == 404:
        return True
    return any(
        token in text
        for token in (
            "404",
            "not found",
            "nosuchkey",
            "no such file",
            "object not found",
        )
    )


async def notify_document_status(
    redis: RedisClient,
    logger: Logger,
    user_id: str,
    document: DocumentResponse,
    notification_service: NotificationService,
) -> None:
    try:
        await notification_service.create_notification(
            CreateNotificationRequest(
                title="Document Status",
                content=document.comment
                or f"{document.name} status changed to {document.status}",
            ),
            user_id,
        )
        await redis.publish_to_user(
            user_id,
            EventPayload(
                type="document.status",
                data={
                    "document_id": document.id,
                    "name": document.name,
                    "status": document.status,
                    "comment": document.comment,
                },
            ),
        )
    except Exception:
        logger.exception(
            "Failed to publish document status notification "
            "user_id=%s document_id=%s status=%s",
            user_id,
            document.id,
            document.status,
        )


async def continue_ingestion(
    document_service: DocumentService,
    document_id: str,
    user_id: str,
    logger: Logger,
    *,
    file_name: str | None = None,
) -> bool:
    try:
        document = await document_service.get_document_by_id(document_id, user_id)
    except ValueError:
        logger.info(
            "Document not found file=%s user_id=%s document_id=%s",
            file_name,
            user_id,
            document_id,
        )
        return False

    if document.status == "completed":
        logger.info(
            "Document already completed file=%s user_id=%s document_id=%s",
            file_name,
            user_id,
            document_id,
        )
        return False
    if document.status == "cancelled":
        logger.info(
            "Document ingestion already cancelled file=%s user_id=%s document_id=%s",
            file_name,
            user_id,
            document_id,
        )
        return False
    return True


def ingest_failure_comment(
    reason: str,
    *,
    exhausted_retries: bool = False,
) -> str:
    """Build a user-facing ingest failure comment from an error reason."""
    because, hint = _classify_ingest_failure(reason)
    if exhausted_retries:
        return (
            f"Ingestion failed after multiple retries because {because}. {hint}"
        )
    return f"Ingestion failed because {because}. {hint}"


def _classify_ingest_failure(reason: str) -> tuple[str, str]:
    text = (reason or "").strip()
    lowered = text.lower()

    if any(
        token in lowered
        for token in (
            "not found",
            "404",
            "no such file",
            "nosuchkey",
            "object not found",
            "file could not be found",
            "couldn't be found",
            "could not be found",
        )
    ):
        return (
            "the file could not be found",
            "Check that the file was uploaded correctly, then retry ingestion.",
        )

    if "unsupported file type" in lowered:
        return (
            "the file type is not supported",
            "Re-upload a supported file and try again. The supported formats are: "
            + _ALLOWED_EXT_HELP,
        )

    if any(
        token in lowered
        for token in (
            "could not be parsed",
            "couldn't be parsed",
            "error loading",
            "failed to parse",
            "parse",
        )
    ):
        return (
            "the file could not be parsed",
            "Re-upload a supported file and try again. The supported formats are: "
            + _ALLOWED_EXT_HELP,
        )

    if any(
        token in lowered
        for token in (
            "no documents",
            "no readable content",
            "empty",
        )
    ):
        return (
            "no readable content was found in the file",
            "Upload a document with extractable text and try again.",
        )

    if "embedding" in lowered:
        return (
            "embeddings could not be generated",
            "Please retry ingestion. Contact support if the problem continues.",
        )

    if "index" in lowered:
        return (
            "the document could not be indexed",
            "Please retry ingestion. Contact support if the problem continues.",
        )

    if text:
        return (
            text.rstrip("."),
            "Please try again, or contact support if the problem continues.",
        )

    return (
        "processing could not be completed",
        "Please try again, or contact support if the problem continues.",
    )


async def process_with_chapters(
    chapter_splitter: ChapterSplitter,
    ingest_pipeline: IngestPipeline,
    payload: IngestDocumentRequest,
    file_path: str,
    logger: Logger,
) -> list[Document]:
    """
    Split into chapters when possible, then chunk each section.
    Falls back to whole-file processing if no chapters are found.
    """
    sections = await asyncio.to_thread(
        chapter_splitter.initiate_chapter_split, file_path
    )
    if not sections:
        logger.info(
            "No chapters detected; processing whole file=%s document_id=%s",
            payload.file_name,
            payload.document_id,
        )
        return await asyncio.to_thread(
            ingest_pipeline.process_file, payload, file_path
        )

    logger.info(
        "Processing %s chapters for file=%s document_id=%s",
        len(sections),
        payload.file_name,
        payload.document_id,
    )

    chunks: list[Document] = []
    section_dirs = {Path(section.file_path).parent for section in sections}

    async def _process_section(section: ParsedSections) -> list[Document]:
        section_chunks = await asyncio.to_thread(
            ingest_pipeline.process_file,
            payload,
            section.file_path,
        )
        for chunk in section_chunks:
            chunk.metadata["chapter"] = section.title
            chunk.metadata["chapter_key"] = section.chapter_key
        logger.info(
            "Processed chapter=%s chapter_key=%s chunks=%s file=%s document_id=%s",
            section.title,
            section.chapter_key,
            len(section_chunks),
            payload.file_name,
            payload.document_id,
        )
        return section_chunks

    try:
        async with asyncio.TaskGroup() as tg:
            tasks = [
                tg.create_task(_process_section(section))
                for section in sections
            ]
        for task in tasks:
            chunks.extend(task.result())
    finally:
        for directory in section_dirs:
            shutil.rmtree(directory, ignore_errors=True)

    for index, chunk in enumerate(chunks):
        chunk.metadata["page"] = f"{chunk.metadata['chapter_key']}_{index}"
        chunk.metadata["id"] = f"{payload.document_id}_{index}"

    return chunks
