import asyncio
import hashlib
import json
import tempfile
from logging import Logger
from pathlib import Path
from time import perf_counter

from aio_pika.abc import AbstractIncomingMessage

from app.core.elasticsearch import Elasticsearch, IndexedDocuments
from app.core.embedding import EmbeddingManager
from app.core.ingest_pipeline import IngestPipeline
from app.core.rabbitmq import RabbitMQ, read_retry_count
from app.core.supabase import Supabase
from app.system.schemas.document import IngestDocumentRequest
from app.system.service.document import DocumentService
from app.utils.errors.rabbitmq import NonRetryableIngestError


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


async def handle_document(
    message: AbstractIncomingMessage,
    ingest_pipeline: IngestPipeline,
    logger: Logger,
    supabase: Supabase,
    document_service: DocumentService,
    embedding_manager: EmbeddingManager,
    elasticsearch: Elasticsearch,
    rabbitmq: RabbitMQ,
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
                await supabase.download_file_to(ingest_payload.path, tmp)
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
                        logger.info(
                            "Document hash already exists file=%s user_id=%s "
                            "document_id=%s existing_id=%s",
                            file_name,
                            user_id,
                            document_id,
                            existing.id,
                        )
                        await document_service.cancel_duplicate(
                            document_id, user_id, existing.path or ""
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
                chunks = await asyncio.to_thread(
                    ingest_pipeline.process_file,
                    ingest_payload,
                    tmp.name,
                )
                end_time = perf_counter()
                logger.info(
                    "Time taken to process file=%s user_id=%s document_id=%s seconds=%s",
                    file_name,
                    user_id,
                    document_id,
                    end_time - start_time,
                )
                if not chunks:
                    await document_service.update_status(
                        document_id, "failed", user_id
                    )
                    raise NonRetryableIngestError("No documents to process")

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
                    await document_service.update_status(
                        document_id, "failed", user_id
                    )
                    raise NonRetryableIngestError("No embeddings to process")

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
                    IndexedDocuments(
                        content=chunk.page_content,
                        metadata=chunk.metadata,
                        embedding=embedding.tolist()
                        if hasattr(embedding, "tolist")
                        else list(embedding),
                    )
                    for chunk, embedding in zip(chunks, embeddings)
                ]
                es_success, _es_failed = await elasticsearch.bulk_index_documents(
                    es_payload
                )
                indexed = es_success > 0
                if not indexed:
                    await elasticsearch.delete_by_document_id(user_id, document_id)
                    raise NonRetryableIngestError("Failed to index documents")
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
                    await elasticsearch.delete_by_document_id(user_id, document_id)
                    indexed = False
                    logger.info(
                        "Cancelled before complete; cleaned indexed docs "
                        "file=%s user_id=%s document_id=%s",
                        file_name,
                        user_id,
                        document_id,
                    )
                    return

                logger.info(
                    "Ingested file=%s user_id=%s document_id=%s",
                    file_name,
                    user_id,
                    document_id,
                )
        except NonRetryableIngestError as e:
            if indexed and user_id and document_id:
                await elasticsearch.delete_by_document_id(user_id, document_id)
            logger.warning(
                "Non-retryable ingest failure file=%s user_id=%s document_id=%s: %s",
                file_name,
                user_id,
                document_id,
                e.message,
            )
            await message.reject(requeue=False)
            return
        except Exception as e:
            if indexed and user_id and document_id:
                await elasticsearch.delete_by_document_id(user_id, document_id)
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
                if user_id and document_id:
                    await document_service.update_status(
                        document_id, "failed", user_id
                    )
                logger.error(
                    "Exhausted retries file=%s user_id=%s document_id=%s "
                    "attempts=%s → DLQ",
                    file_name,
                    user_id,
                    document_id,
                    retry_count,
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
