import hashlib
import json
import tempfile
from logging import Logger
from pathlib import Path

from aio_pika.abc import AbstractIncomingMessage

from app.core.embedding import EmbeddingManager
from app.core.ingest_pipeline import IngestPipeline
from app.core.supabase import Supabase
from app.core.vector_store import VectorStore
from app.system.schemas.document import IngestDocumentRequest
from app.system.service.document import DocumentService
from app.utils.errors.rabbitmq import NonRetryableIngestError


async def continue_ingestion(
    document_service: DocumentService,
    document_id: str,
    user_id: str,
    logger: Logger,
) -> bool:
    try:
        document = await document_service.get_document_by_id(document_id, user_id)
    except ValueError:
        logger.info("Document not found: %s", document_id)
        return False

    if document.status == "completed":
        logger.info("Document already completed: %s", document_id)
        return False
    if document.status == "cancelled":
        logger.info("Document ingestion already cancelled: %s", document_id)
        return False
    return True


def cleanup_vectors(
    vector_ids: list[str],
    user_id: str,
    vector_store: VectorStore,
) -> None:
    if vector_ids:
        vector_store.delete_document_by_ids(vector_ids, user_id)


async def handle_document(
    message: AbstractIncomingMessage,
    ingest_pipeline: IngestPipeline,
    logger: Logger,
    supabase: Supabase,
    document_service: DocumentService,
    embedding_manager: EmbeddingManager,
    vector_store: VectorStore,
) -> None:
    document_id: str | None = None
    user_id: str | None = None
    vector_ids: list[str] = []

    async with message.process():
        try:
            payload = json.loads(message.body)
            ingest_payload = IngestDocumentRequest(**payload)
            document_id = ingest_payload.document_id
            user_id = ingest_payload.user_id

            claimed = await document_service.claim_for_processing(
                document_id, user_id
            )
            if claimed is None:
                logger.info(
                    "Skipping ingest; could not claim document %s", document_id
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
                                "Document %s no longer processing; skip complete or cancelled",
                                document_id,
                            )
                    else:
                        logger.info(
                            "Document hash already exists for id=%s", existing.id
                        )
                        await document_service.update_status(
                            document_id, "cancelled", user_id
                        )
                    return

                if not await continue_ingestion(
                    document_service, document_id, user_id, logger
                ):
                    return

                tmp.seek(0)
                chunks = await ingest_pipeline.process_file(ingest_payload, tmp)
                if not chunks:
                    await document_service.update_status(
                        document_id, "failed", user_id
                    )
                    raise NonRetryableIngestError("No documents to process")

                if not await continue_ingestion(
                    document_service, document_id, user_id, logger
                ):
                    return

                embeddings = embedding_manager.embed_documents(chunks)
                if not embeddings:
                    await document_service.update_status(
                        document_id, "failed", user_id
                    )
                    raise NonRetryableIngestError("No embeddings to process")

                if not await continue_ingestion(
                    document_service, document_id, user_id, logger
                ):
                    return

                vector_ids = vector_store.add_documents(chunks, embeddings)

                completed = await document_service.complete_document(
                    document_id, user_id, file_hash
                )
                if completed is None:
                    cleanup_vectors(vector_ids, user_id, vector_store)
                    vector_ids = []
                    logger.info(
                        "Cancelled before complete; cleaned vectors for %s",
                        document_id,
                    )
                    return

                logger.info(
                    "Ingested document: %s for user %s", document_id, user_id
                )
        except NonRetryableIngestError as e:
            if vector_ids and user_id is not None:
                cleanup_vectors(vector_ids, user_id, vector_store)
            logger.warning(
                "Non-retryable ingest failure: %s for user %s",
                e.message,
                user_id,
            )
        except Exception:
            if vector_ids and user_id is not None:
                cleanup_vectors(vector_ids, user_id, vector_store)
            logger.exception(
                "Error ingesting document for user %s", user_id
            )
            raise
