import asyncio
import uuid
from datetime import datetime, timezone
from logging import Logger

from langchain_core.documents import Document
from langchain_google_genai import ChatGoogleGenerativeAI
from trustcall import create_extractor

from app.core.embedding import EmbeddingManager
from app.utils.llm import is_rate_limit_error
from app.memory.prompts import memory_search_query_prompt, memory_trustcall_prompt
from app.memory.repository import MemoryRepository
from app.memory.schema import (
    DOCUMENT_SCOPED_CATEGORIES,
    DEFAULT_LIST_LIMIT,
    MAX_LIST_LIMIT,
    ExtractedMemory,
    Memory,
    MemoryListResponseData,
    MemoryResponse,
    MemoryRetrievalQuery,
    MemorySearch,
    MemorySearchQueryResult,
)

_EXTRACTED_MEMORY_TOOL = "ExtractedMemory"


class MemoryService:
    def __init__(
        self,
        logger: Logger,
        model: ChatGoogleGenerativeAI,
        repository: MemoryRepository,
        embedding_manager: EmbeddingManager,
    ):
        self.logger = logger
        self.model = model
        self.repository = repository
        self.embedding_manager = embedding_manager
        self._extractor = create_extractor(
            model,
            tools=[ExtractedMemory],
            tool_choice="any",
            enable_inserts=True,
            enable_deletes=True,
        )

    async def retrieve(self, search: MemorySearch) -> list[Memory]:
        try:
            self.logger.info(
                "MemoryService retrieve start user_id=%s "
                "category=%s document_id=%s",
                search.user_id,
                search.category,
                search.document_id,
            )
            results = await self.repository.retrieve(search)
            self.logger.info(
                "MemoryService retrieve done results=%s",
                len(results),
            )
            return results
        except Exception as e:
            self.logger.exception(f"MemoryService retrieve failed: {e}")
            raise ValueError("Failed to retrieve") from e

    async def list_by_user(
        self,
        user_id: str,
        *,
        limit: int = DEFAULT_LIST_LIMIT,
        cursor: str | None = None,
    ) -> MemoryListResponseData:
        try:
            self.logger.info(
                "MemoryService list start user_id=%s limit=%s has_cursor=%s",
                user_id,
                limit,
                cursor is not None,
            )
            memories, next_cursor, has_more = await self.repository.list_by_user(
                user_id,
                limit=limit,
                cursor=cursor,
            )
            clamped = min(max(limit, 1), MAX_LIST_LIMIT)
            self.logger.info(
                "MemoryService list done user_id=%s count=%s has_more=%s",
                user_id,
                len(memories),
                has_more,
            )
            return MemoryListResponseData(
                items=[
                    MemoryResponse(
                        id=memory.id,
                        content=memory.content,
                        category=memory.category,
                        document_id=memory.document_id,
                        created_at=memory.created_at,
                        updated_at=memory.updated_at,
                        expires_at=memory.expires_at,
                    )
                    for memory in memories
                ],
                next_cursor=next_cursor,
                has_more=has_more,
                limit=clamped,
            )
        except ValueError:
            raise
        except Exception as e:
            self.logger.exception(f"MemoryService list failed: {e}")
            raise ValueError("Failed to list memories") from e

    async def retrieve_for_queries(
        self,
        user_id: str,
        queries: list[MemoryRetrievalQuery],
    ) -> list[Memory]:
        """Batch-embed queries, search in parallel, and dedupe by id."""
        if not queries:
            return []

        try:
            self.logger.info(
                "MemoryService retrieve_for_queries start user_id=%s "
                "queries=%s",
                user_id,
                len(queries),
            )
            embeddings = await self._embed_contents(
                [query.content for query in queries]
            )

            async with asyncio.TaskGroup() as tg:
                tasks = [
                    tg.create_task(
                        self.retrieve(
                            MemorySearch(
                                user_id=user_id,
                                content=query.content,
                                embedding=embedding,
                                category=query.category,
                                document_id=query.document_id,
                            )
                        )
                    )
                    for query, embedding in zip(queries, embeddings)
                ]

            by_id: dict[str, Memory] = {}
            for task in tasks:
                for memory in task.result():
                    by_id[memory.id] = memory

            self.logger.info(
                "MemoryService retrieve_for_queries done results=%s",
                len(by_id),
            )
            return list(by_id.values())
        except Exception as e:
            self.logger.exception(
                f"MemoryService retrieve_for_queries failed: {e}"
            )
            raise ValueError("Failed to retrieve") from e

    async def store(
        self,
        user_id: str,
        context: str,
        *,
        known_memories: list[str] | None = None,
        document_id: str | None = None,
        conversation_id: str | None = None,
    ):
        try:
            queries = await self.extract_search_queries(
                context,
                known_memories=known_memories,
                document_id=document_id,
                conversation_id=conversation_id,
            )
            existing = await self.retrieve_for_queries(user_id, queries)
            updated, created, deleted = await self.apply_trustcall(
                user_id=user_id,
                context=context,
                existing=existing,
                document_id=document_id,
                conversation_id=conversation_id,
            )
            if not updated and not created and not deleted:
                return None

            async with asyncio.TaskGroup() as tg:
                update_task = tg.create_task(self.update_metadata(updated))
                delete_task = tg.create_task(self.delete(deleted))
                create_task = tg.create_task(self.create(created))

            return (
                update_task.result(),
                delete_task.result(),
                create_task.result(),
            )
        except Exception as e:
            self.logger.exception(f"MemoryService store failed: {e}")
            raise ValueError("Failed to store") from e

    async def extract_search_queries(
        self,
        context: str,
        *,
        known_memories: list[str] | None = None,
        document_id: str | None = None,
        conversation_id: str | None = None,
    ) -> list[MemoryRetrievalQuery]:
        prompt = memory_search_query_prompt(
            context=context,
            known_memories=known_memories,
            document_id=document_id,
            now=datetime.now(timezone.utc),
        )
        config = None
        if conversation_id:
            config = {
                "configurable": {"thread_id": conversation_id},
                "metadata": {"thread_id": conversation_id},
            }
        try:
            result: MemorySearchQueryResult = (
                await self.model.with_structured_output(
                    MemorySearchQueryResult
                ).ainvoke(
                    prompt,
                    config,
                )
            )
        except Exception as e:
            if is_rate_limit_error(e):
                self.logger.warning("Memory search query extraction rate limited")
            else:
                self.logger.exception("Memory search query extraction failed")
            return []

        self.logger.info(
            "Extracted %s memory search queries",
            len(result.queries),
        )
        return result.queries

    async def apply_trustcall(
        self,
        user_id: str,
        context: str,
        existing: list[Memory],
        *,
        document_id: str | None = None,
        conversation_id: str | None = None,
    ) -> tuple[list[Memory], list[Memory], list[Memory]]:
        """Run trustcall over existing memories; return (updated, created, deleted)."""
        now = datetime.now(timezone.utc)
        prompt = memory_trustcall_prompt(
            context=context,
            existing=existing,
            document_id=document_id,
            now=now,
        )
        existing_payload = [
            (
                memory.id,
                _EXTRACTED_MEMORY_TOOL,
                ExtractedMemory(
                    content=memory.content,
                    category=memory.category,
                    expires_at=memory.expires_at,
                    document_id=memory.document_id,
                ).model_dump(mode="json"),
            )
            for memory in existing
        ]

        config = None
        if conversation_id:
            config = {
                "configurable": {"thread_id": conversation_id},
                "metadata": {"thread_id": conversation_id},
            }

        try:
            result = await self._extractor.ainvoke(
                {
                    "messages": [{"role": "user", "content": prompt}],
                    "existing": existing_payload or None,
                },
                config=config,
            )
        except Exception as e:
            if is_rate_limit_error(e):
                self.logger.warning("Memory trustcall rate limited")
            else:
                self.logger.exception("Memory trustcall failed")
            raise ValueError("Failed to apply trustcall") from e

        existing_by_id = {memory.id: memory for memory in existing}
        updated: list[Memory] = []
        created_extracted: list[ExtractedMemory] = []
        deleted: list[Memory] = []

        for response, meta in zip(
            result.get("responses") or [],
            result.get("response_metadata") or [],
        ):
            # Delete trustcall responses only carry json_doc_id.
            if not hasattr(response, "content"):
                doc_id = getattr(response, "json_doc_id", None)
                memory = existing_by_id.get(doc_id) if doc_id else None
                if memory is None:
                    continue
                deleted.append(memory)
                continue

            extracted = (
                response
                if isinstance(response, ExtractedMemory)
                else ExtractedMemory.model_validate(response)
            )
            json_doc_id = meta.get("json_doc_id")
            if json_doc_id and json_doc_id in existing_by_id:
                memory = existing_by_id[json_doc_id]
                memory.content = extracted.content
                memory.category = extracted.category
                memory.expires_at = extracted.expires_at
                memory.document_id = _resolve_document_id(extracted)
                memory.updated_at = now
                updated.append(memory)
            else:
                created_extracted.append(extracted)

        if updated:
            embeddings = await self._embed_contents(
                [memory.content for memory in updated]
            )
            for memory, embedding in zip(updated, embeddings):
                memory.embedding = embedding

        created = await self._to_memories(user_id, created_extracted)

        self.logger.info(
            "MemoryService trustcall done updated=%s created=%s deleted=%s",
            len(updated),
            len(created),
            len(deleted),
        )
        return updated, created, deleted

    async def create(self, memories: list[Memory]) -> tuple[int, int]:
        try:
            if not memories:
                return 0, 0
            self.logger.info(
                "MemoryService create start memories=%s",
                len(memories),
            )
            success, failed = await self.repository.store(memories)
            self.logger.info(
                "MemoryService create done success=%s failed=%s",
                success,
                failed,
            )
            return success, failed
        except Exception as e:
            self.logger.exception(f"MemoryService create failed: {e}")
            raise ValueError("Failed to create") from e

    async def update_metadata(self, memories: list[Memory]) -> tuple[int, int]:
        try:
            if not memories:
                return 0, 0
            self.logger.info(
                "MemoryService update_metadata start memories=%s",
                len(memories),
            )
            success, failed = await self.repository.update(memories)
            self.logger.info(
                "MemoryService update done success=%s failed=%s",
                success, failed)
            return success, failed
        except Exception as e:
            self.logger.exception(f"MemoryService update_metadata failed: {e}")
            raise ValueError("Failed to update metadata") from e


    async def delete(self, memories: list[Memory]) -> tuple[int, int]:
        try:
            if not memories:
                return 0, 0
            self.logger.info(
                "MemoryService delete start memories=%s",
                len(memories),
            )
            success, failed = await self.repository.delete(
                [memory.id for memory in memories]
            )
            self.logger.info(
                "MemoryService delete done success=%s failed=%s",
                success, failed)
            return success, failed
        except Exception as e:
            self.logger.exception(f"MemoryService delete failed: {e}")
            raise ValueError("Failed to delete") from e

    async def _embed_contents(self, contents: list[str]) -> list[list[float]]:
        if not contents:
            return []
        embeddings = await asyncio.to_thread(
            self.embedding_manager.embed_documents,
            [Document(page_content=content) for content in contents],
        )
        return [
            embedding.tolist() if hasattr(embedding, "tolist") else list(embedding)
            for embedding in embeddings
        ]

    async def _to_memories(
        self,
        user_id: str,
        candidates: list[ExtractedMemory],
    ) -> list[Memory]:
        if not candidates:
            return []

        embeddings = await self._embed_contents(
            [candidate.content for candidate in candidates]
        )
        return [
            Memory(
                id=str(uuid.uuid4()),
                user_id=user_id,
                content=candidate.content,
                embedding=embedding,
                category=candidate.category,
                expires_at=candidate.expires_at,
                document_id=_resolve_document_id(candidate),
            )
            for candidate, embedding in zip(candidates, embeddings)
        ]


def _resolve_document_id(extracted: ExtractedMemory) -> str | None:
    if extracted.category not in DOCUMENT_SCOPED_CATEGORIES:
        return None
    return extracted.document_id
