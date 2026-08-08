import asyncio
from dataclasses import dataclass
import shutil
from logging import Logger
from pathlib import Path
from typing import TYPE_CHECKING

from app.utils.errors.rabbitmq import NonRetryableIngestError
from langchain_core.documents import Document

from app.core.redis import RedisClient
from app.rag.chapter_splitter import ChapterSplitter
from app.rag.ingest_pipeline import IngestPipeline
from app.rag.schema import ParsedSections
from app.system.document.schema import IngestDocumentRequest
from app.system.notification.schema import CreateNotificationRequest, EventPayload
from app.system.notification.service import NotificationService

if TYPE_CHECKING:
    from app.system.document.service import DocumentService

@dataclass
class ProcessWithChaptersResult:
    chunks: list[Document]
    sections: list[str] | None


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
    notification_service: NotificationService,
    *,
    document_id: str,
    name: str | None,
    status: str,
    comment: str | None = None,
) -> None:
    try:
        await notification_service.create_notification(
            CreateNotificationRequest(
                title="Document Status",
                content=comment
                or f"{name or 'Document'} status changed to {status}",
            ),
            user_id,
        )
        await redis.publish_to_user(
            user_id,
            EventPayload(
                type="document.status",
                data={
                    "document_id": document_id,
                    "name": name,
                    "status": status,
                    "comment": comment,
                },
            ),
        )
    except Exception:
        logger.exception(
            "Failed to publish document status notification "
            "user_id=%s document_id=%s status=%s",
            user_id,
            document_id,
            status,
        )


async def continue_ingestion(
    document_service: "DocumentService",
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


async def process_with_chapters(
    chapter_splitter: ChapterSplitter,
    ingest_pipeline: IngestPipeline,
    payload: IngestDocumentRequest,
    file_path: str,
    logger: Logger,
) -> ProcessWithChaptersResult:
    """
    Split into chapters when possible, then chunk each section.
    Throws NonRetryableIngestError if no chapters are found.
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
        raise NonRetryableIngestError("Document has no chapters.")

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
        # ES maps metadata.page as integer; keep chapter identity in chapter_key.
        chunk.metadata["page"] = index
        chunk.metadata["id"] = f"{payload.document_id}_{index}"

    chapters = [section.chapter_key for section in sections]

    return ProcessWithChaptersResult(chunks, chapters)
