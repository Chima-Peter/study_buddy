import asyncio
import hashlib
import json
import tempfile
from logging import Logger
from pathlib import Path
from time import perf_counter
from typing import cast

from aio_pika.abc import AbstractIncomingMessage

from app.core.elasticsearch import Elasticsearch
from app.core.elasticsearch_schema import DocumentMetadata, IndexedRecord
from app.core.embedding import EmbeddingManager
from app.handlers.document.util import (
    continue_ingestion,
    is_file_not_found_error,
    notify_document_status,
    process_with_chapters,
)
from app.core.rabbitmq import RabbitMQ, read_retry_count
from app.core.redis import RedisClient
from app.core.supabase import Supabase
from app.rag.chapter_splitter import ChapterSplitter
from app.rag.ingest_pipeline import IngestPipeline
from app.system.schemas.document import (
    IngestDocumentRequest,
    ingest_failure_comment,
)
from app.system.service.document import DocumentService
from app.system.service.notification import NotificationService
from app.utils.errors.rabbitmq import NonRetryableIngestError


async def handle_document(
    message: AbstractIncomingMessage,
    ingest_pipeline: IngestPipeline,
    chapter_splitter: ChapterSplitter,
    logger: Logger,
    supabase: Supabase,
    document_service: DocumentService,
    embedding_manager: EmbeddingManager,
    elasticsearch: Elasticsearch,
    rabbitmq: RabbitMQ,
    redis: RedisClient,
    notification_service: NotificationService,
) -> None:
    document_id: str | None = None
    user_id: str | None = None
    file_name: str | None = None
    indexed = False
    payload: dict | None = None

    # requeue=False: soft failures schedule TTL backoff instead of immediate redelivery
    async with message.process(requeue=False, ignore_processed=True):
        try:
            payload = json.loads(message.body)
            ingest_payload = IngestDocumentRequest(**payload)
            document_id = ingest_payload.document_id
            user_id = ingest_payload.user_id
            file_name = ingest_payload.file_name
            retry_count = read_retry_count(message.headers)

            logger.info(
                "Received ingest message file=%s user_id=%s document_id=%s retry=%s",
                file_name,
                user_id,
                document_id,
                retry_count,
            )

            claimed = await document_service.claim_for_processing(
                document_id, user_id
            )
            if claimed is None:
                logger.info(
                    "Skipping ingest; could not claim file=%s user_id=%s document_id=%s",
                    file_name,
                    user_id,
                    document_id,
                )
                return

            suffix = (
                Path(ingest_payload.file_name).suffix
                or Path(ingest_payload.path).suffix
            )

            with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
                try:
                    await supabase.download_file_to(ingest_payload.path, tmp)
                except Exception as download_error:
                    if is_file_not_found_error(download_error):
                        raise NonRetryableIngestError(
                            f"File could not be found at path {ingest_payload.path}"
                        ) from download_error
                    raise
                tmp.flush()
                tmp.seek(0)

                file_hash = hashlib.sha256(tmp.read()).hexdigest()
                existing = await document_service.get_document_by_hash(
                    file_hash, user_id
                )
                if existing is not None:
                    if existing.id == document_id:
                        completed = await document_service.complete_document(
                            document_id, user_id, file_hash
                        )
                        if completed is None:
                            logger.info(
                                "Document no longer processing; skip complete "
                                "file=%s user_id=%s document_id=%s",
                                file_name,
                                user_id,
                                document_id,
                            )
                        else:
                            await notify_document_status(
                                redis, logger, user_id, completed, notification_service
                            )
                    else:
                        logger.info(
                            "Document hash already exists file=%s user_id=%s "
                            "document_id=%s existing_id=%s",
                            file_name,
                            user_id,
                            document_id,
                            existing.id,
                        )
                        cancelled = await document_service.cancel_duplicate(
                            document_id, user_id, existing.path or ""
                        )
                        await notify_document_status(
                            redis, logger, user_id, cancelled, notification_service
                        )
                        if (
                            ingest_payload.path
                            and ingest_payload.path != existing.path
                        ):
                            await supabase.delete_file(ingest_payload.path)
                    return

                if not await continue_ingestion(
                    document_service,
                    document_id,
                    user_id,
                    logger,
                    file_name=file_name,
                ):
                    return

                start_time = perf_counter()
                chunks = await process_with_chapters(
                    chapter_splitter,
                    document_service,
                    ingest_pipeline,
                    ingest_payload,
                    tmp.name,
                    logger,
                )
                end_time = perf_counter()
                logger.info(
                    "Time taken to process file=%s user_id=%s document_id=%s "
                    "seconds=%s chunks=%s",
                    file_name,
                    user_id,
                    document_id,
                    end_time - start_time,
                    len(chunks) if chunks else 0,
                )
                if not chunks:
                    raise NonRetryableIngestError(
                        "No readable content was found in the file"
                    )

                if not await continue_ingestion(
                    document_service,
                    document_id,
                    user_id,
                    logger,
                    file_name=file_name,
                ):
                    return

                start_time = perf_counter()
                embeddings = await asyncio.to_thread(
                    embedding_manager.embed_documents, chunks
                )
                end_time = perf_counter()
                logger.info(
                    "Time taken to embed file=%s user_id=%s document_id=%s seconds=%s",
                    file_name,
                    user_id,
                    document_id,
                    end_time - start_time,
                )
                if embeddings is None or len(embeddings) == 0:
                    raise NonRetryableIngestError(
                        "No embeddings could be generated for the file"
                    )

                if not await continue_ingestion(
                    document_service,
                    document_id,
                    user_id,
                    logger,
                    file_name=file_name,
                ):
                    return

                start_time = perf_counter()
                es_payload = [
                    IndexedRecord(
                        content=chunk.page_content,
                        metadata=cast(DocumentMetadata, chunk.metadata),
                        embedding=embedding.tolist()
                        if hasattr(embedding, "tolist")
                        else list(embedding),
                    )
                    for chunk, embedding in zip(chunks, embeddings)
                ]
                es_success, _es_failed = await elasticsearch.bulk_index(
                    es_payload, index="documents"
                )
                indexed = es_success > 0
                if not indexed:
                    await elasticsearch.delete_by_metadata(
                        user_id, index="documents", document_id=document_id
                    )
                    raise NonRetryableIngestError(
                        "Document could not be indexed into search"
                    )
                end_time = perf_counter()
                logger.info(
                    "Time taken to index file=%s user_id=%s document_id=%s seconds=%s",
                    file_name,
                    user_id,
                    document_id,
                    end_time - start_time,
                )

                completed = await document_service.complete_document(
                    document_id, user_id, file_hash
                )
                if completed is None:
                    await elasticsearch.delete_by_metadata(
                        user_id, index="documents", document_id=document_id
                    )
                    indexed = False
                    logger.info(
                        "Cancelled before complete; cleaned indexed docs "
                        "file=%s user_id=%s document_id=%s",
                        file_name,
                        user_id,
                        document_id,
                    )
                    return

                await notify_document_status(redis, logger, user_id, completed, notification_service)
                logger.info(
                    "Ingested file=%s user_id=%s document_id=%s",
                    file_name,
                    user_id,
                    document_id,
                )
        except NonRetryableIngestError as e:
            if indexed and user_id and document_id:
                await elasticsearch.delete_by_metadata(
                    user_id, index="documents", document_id=document_id
                )
            reason = e.message or str(e)
            comment = ingest_failure_comment(reason)
            logger.warning(
                "Non-retryable ingest failure file=%s user_id=%s document_id=%s: %s",
                file_name,
                user_id,
                document_id,
                reason,
            )
            if user_id and document_id:
                failed = await document_service.update_status(
                    document_id,
                    "failed",
                    user_id,
                    from_statuses=("pending", "processing", "failed"),
                    comment=comment,
                )
                if failed is not None:
                    await notify_document_status(redis, logger, user_id, failed, notification_service)
            await message.reject(requeue=False)
            return
        except Exception as e:
            if indexed and user_id and document_id:
                await elasticsearch.delete_by_metadata(
                    user_id, index="documents", document_id=document_id
                )
            logger.exception(
                "Error ingesting file=%s user_id=%s document_id=%s: %s",
                file_name,
                user_id,
                document_id,
                e,
            )
            if payload is None:
                await message.reject(requeue=False)
                return

            retry_count = read_retry_count(message.headers)
            if retry_count >= rabbitmq.max_retries:
                comment = ingest_failure_comment(
                    str(e),
                    exhausted_retries=True,
                )
                if user_id and document_id:
                    failed = await document_service.update_status(
                        document_id,
                        "failed",
                        user_id,
                        from_statuses=("pending", "processing", "failed"),
                        comment=comment,
                    )
                logger.error(
                    "Exhausted retries file=%s user_id=%s document_id=%s "
                    "attempts=%s comment=%s → DLQ",
                    file_name,
                    user_id,
                    document_id,
                    retry_count,
                    comment,
                )
                await message.reject(requeue=False)
                return

            await rabbitmq.schedule_retry(
                "document_queue",
                payload,
                retry_count=retry_count,
                headers=message.headers,
            )
            return
