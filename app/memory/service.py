import asyncio
import uuid
from datetime import datetime, timezone
from logging import Logger

from langchain_core.documents import Document
from langchain_google_genai import ChatGoogleGenerativeAI

from app.core.embedding import EmbeddingManager
from app.utils.llm import is_rate_limit_error
from app.memory.prompts import memory_deduplication_prompt, memory_extraction_prompt
from app.memory.repository import MemoryRepository
from app.memory.schema import (
    CONFIDENCE_BUMP,
    ExtractedMemory,
    Memory,
    MemoryDeduplicationDecision,
    MemoryDeduplicationResult,
    MemoryDuplicateSearch,
    MemoryExtractionResult,
    MEMORY_STATUS,
    MemoryRetrievalQuery,
    MemorySearch,
)


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

    async def retrieve(self, search: MemorySearch) -> list[Memory]:
        try:
            self.logger.info(
                "MemoryService retrieve start user_id=%s status=%s",
                search.user_id,
                search.status,
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

    async def retrieve_for_queries(
        self,
        user_id: str,
        queries: list[MemoryRetrievalQuery],
        *,
        status: MEMORY_STATUS = "active",
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
                                status=status,
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
    ):
        try:
            extracted = await self.extract_candidate_memories(
                context,
                known_memories=known_memories,
            )
            if not extracted:
                return None

            candidates = await self._to_memories(user_id, extracted)
            related_by_candidate = await self.search_duplicates_for_candidates(
                user_id, candidates
            )
            deduped = await self.deduplicate(
                candidates=candidates,
                related_by_candidate=related_by_candidate,
            )

            async with asyncio.TaskGroup() as tg:
                identical_task = tg.create_task(
                    self.update_metadata(deduped.identical)
                )
                supersede_task = tg.create_task(
                    self.update_metadata(
                        [*deduped.superseded, *deduped.archived]
                    )
                )
                create_task = tg.create_task(
                    self.create(
                        [
                            *deduped.updated,
                            *deduped.different,
                            *deduped.contradict,
                        ]
                    )
                )

            return (
                identical_task.result(),
                supersede_task.result(),
                create_task.result(),
            )
        except Exception as e:
            self.logger.exception(f"MemoryService store failed: {e}")
            raise ValueError("Failed to store") from e

    async def extract_candidate_memories(
        self,
        context: str,
        *,
        known_memories: list[str] | None = None,
    ) -> list[ExtractedMemory]:
        prompt = memory_extraction_prompt(
            context=context,
            known_memories=known_memories,
            now=datetime.now(timezone.utc),
        )
        try:
            result: MemoryExtractionResult = (
                await self.model.with_structured_output(
                    MemoryExtractionResult
                ).ainvoke(prompt)
            )
        except Exception as e:
            if is_rate_limit_error(e):
                self.logger.warning("Memory extraction rate limited")
            else:
                self.logger.exception("Memory extraction failed")
            return []

        self.logger.info("Extracted %s memory candidates", len(result.memories))
        return result.memories

    async def search_duplicates_for_candidates(
        self,
        user_id: str,
        candidates: list[Memory],
    ) -> dict[str, list[Memory]]:
        """Map each candidate id to its related active memories from vector search."""
        if not candidates:
            return {}

        async with asyncio.TaskGroup() as tg:
            tasks = [
                tg.create_task(
                    self.search_for_duplicates(
                        MemoryDuplicateSearch(
                            user_id=user_id,
                            content=candidate.content,
                            embedding=candidate.embedding,
                            category=candidate.category,
                        )
                    )
                )
                for candidate in candidates
            ]

        return {
            candidate.id: task.result()
            for candidate, task in zip(candidates, tasks)
        }

    async def deduplicate(
        self,
        candidates: list[Memory],
        related_by_candidate: dict[str, list[Memory]],
    ) -> MemoryDeduplicationResult:
        try:
            related_count = sum(
                len(related) for related in related_by_candidate.values()
            )
            self.logger.info(
                "MemoryService deduplicate start candidates=%s related=%s",
                len(candidates),
                related_count,
            )
            decision: MemoryDeduplicationDecision = (
                await self.model.with_structured_output(
                    MemoryDeduplicationDecision
                ).ainvoke(
                    memory_deduplication_prompt(
                        candidates, related_by_candidate
                    )
                )
            )

            candidates_by_id = {memory.id: memory for memory in candidates}
            existing_by_id: dict[str, Memory] = {}
            for related in related_by_candidate.values():
                for memory in related:
                    existing_by_id[memory.id] = memory

            now = datetime.now(timezone.utc)
            identical: list[Memory] = []
            for item in decision.identical:
                if not item.verified:
                    continue
                memory = existing_by_id.get(item.existing_id)
                if memory is None:
                    continue
                memory.confidence = min(1.0, memory.confidence + CONFIDENCE_BUMP)
                memory.updated_at = now
                identical.append(memory)

            superseded: list[Memory] = []
            updated: list[Memory] = []
            for item in decision.updated:
                old = existing_by_id.get(item.existing_id)
                candidate = candidates_by_id.get(item.candidate_id)
                if old is None or candidate is None:
                    continue
                old.status = "superseded"
                old.valid_to = now
                old.updated_at = now
                superseded.append(old)

                candidate.valid_from = now
                updated.append(candidate)

            different = [
                candidates_by_id[item.candidate_id]
                for item in decision.different
                if item.candidate_id in candidates_by_id
            ]

            archived: list[Memory] = []
            contradict: list[Memory] = []
            for item in decision.contradict:
                old = existing_by_id.get(item.existing_id)
                candidate = candidates_by_id.get(item.candidate_id)
                if old is None or candidate is None:
                    continue
                old.status = "archived"
                old.valid_to = now
                old.updated_at = now
                archived.append(old)
                contradict.append(candidate)

            self.logger.info(
                "MemoryService deduplicate done identical=%s superseded=%s "
                "archived=%s updated=%s different=%s contradict=%s",
                len(identical),
                len(superseded),
                len(archived),
                len(updated),
                len(different),
                len(contradict),
            )
            return MemoryDeduplicationResult(
                identical=identical,
                superseded=superseded,
                archived=archived,
                updated=updated,
                different=different,
                contradict=contradict,
            )
        except Exception as e:
            if is_rate_limit_error(e):
                self.logger.warning("MemoryService deduplicate rate limited")
            else:
                self.logger.exception(f"MemoryService deduplicate failed: {e}")
            raise ValueError("Failed to deduplicate") from e

    async def search_for_duplicates(
        self, search: MemoryDuplicateSearch
    ) -> list[Memory]:
        try:
            self.logger.info(
                "MemoryService search_for_duplicates start user_id=%s "
                "category=%s",
                search.user_id,
                search.category,
            )
            results = await self.repository.search_for_duplicates(search)
            self.logger.info(
                "MemoryService search_for_duplicates done results=%s",
                len(results),
            )
            return results
        except Exception as e:
            self.logger.exception(f"MemoryService search_for_duplicates failed: {e}")
            raise ValueError("Failed to search for duplicates") from e

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

    async def consolidate(self):
        pass

    async def reflect(self):
        pass

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

    async def forget(self, memories: list[Memory]) -> tuple[int, int]:
        try:
            if not memories:
                return 0, 0
            self.logger.info(
                "MemoryService forget start memories=%s",
                len(memories),
            )
            for memory in memories:
                memory.status = "archived"
            success, failed = await self.update_metadata(memories)
            self.logger.info(
                "MemoryService forget done success=%s failed=%s",
                success, failed)
            return success, failed
        except Exception as e:
            self.logger.exception(f"MemoryService forget failed: {e}")
            raise ValueError("Failed to forget") from e

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
        now = datetime.now(timezone.utc)
        return [
            Memory(
                id=str(uuid.uuid4()),
                user_id=user_id,
                content=candidate.content,
                embedding=embedding,
                category=candidate.category,
                importance=candidate.importance,
                confidence=candidate.confidence,
                source="conversation",
                valid_from=now,
                expires_at=candidate.expires_at,
            )
            for candidate, embedding in zip(candidates, embeddings)
        ]
