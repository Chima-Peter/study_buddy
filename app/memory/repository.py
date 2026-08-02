from logging import Logger
from typing import cast

from app.core.elasticsearch import Elasticsearch
from app.core.elasticsearch_schema import IndexedRecord, MemoryMetadata
from app.core.retriever import Retriever
from app.memory.schema import DUPLICATE_MIN_SCORE, DUPLICATE_TOP_K, MEMORY_INDEX, SEARCH_TOP_K, Memory, MemoryDuplicateSearch, MemorySearch



class MemoryRepository:
    def __init__(self, logger: Logger, elasticsearch: Elasticsearch):
        self.logger = logger
        self.elasticsearch = elasticsearch
        self.retriever = Retriever(logger)

    def _to_indexed_record(self, memory: Memory) -> IndexedRecord:
        return IndexedRecord(
            content=memory.content,
            metadata=cast(
                MemoryMetadata,
                memory.model_dump(exclude={"content", "embedding"}),
            ),
            embedding=memory.embedding,
        )

    def _from_indexed_record(self, record: IndexedRecord) -> Memory:
        return Memory.model_validate(
            {
                **cast(MemoryMetadata, record.metadata),
                "content": record.content,
                "embedding": record.embedding,
            }
        )

    async def retrieve(self, search: MemorySearch) -> list[Memory]:
        try:
            self.logger.info(
                "MemoryRepository search start user_id=%s status=%s",
                search.user_id,
                search.status,
            )

            results_lists = await self.elasticsearch.search_hybrid(
                search.user_id,
                search.content,
                search.embedding,
                index=MEMORY_INDEX,
                min_score=None,
                status=search.status,
            )
            fused = await self.retriever.reciprocal_rank_fusion(
                results_lists,
                k=SEARCH_TOP_K,
            )
            results = [
                self._from_indexed_record(result.document) for result in fused
            ]

            self.logger.info(
                "MemoryRepository search done user_id=%s hits=%s",
                search.user_id,
                len(results),
            )
            return results
        except Exception as e:
            self.logger.exception("MemoryRepository search failed: %s", e)
            raise ValueError("Failed to search") from e

    async def search_for_duplicates(
        self, search: MemoryDuplicateSearch
    ) -> list[Memory]:
        try:
            self.logger.info(
                "MemoryRepository search_for_duplicates start user_id=%s "
                "category=%s",
                search.user_id,
                search.category,
            )

            results = await self.elasticsearch.search_vector(
                user_id=search.user_id,
                embedding=search.embedding,
                index=MEMORY_INDEX,
                k=DUPLICATE_TOP_K,
                min_score=DUPLICATE_MIN_SCORE,
                category=search.category,
                status="active",
            )

            self.logger.info(
                "MemoryRepository search_for_duplicates done user_id=%s hits=%s",
                search.user_id,
                len(results),
            )
            return [self._from_indexed_record(result) for result in results]
        except Exception as e:
            self.logger.exception(
                "MemoryRepository search_for_duplicates failed: %s", e
            )
            raise ValueError("Failed to search for duplicates") from e

    async def store(self, memories: list[Memory]) -> tuple[int, int]:
        try:
            self.logger.info(
                "MemoryRepository store start memories=%s",
                len(memories),
            )

            success, failed = await self.elasticsearch.bulk_index(
                [self._to_indexed_record(memory) for memory in memories],
                index=MEMORY_INDEX,
            )
            self.logger.info(
                "MemoryRepository store done success=%s failed=%s",
                success,
                failed,
            )
            return success, failed
        except Exception as e:
            self.logger.exception("MemoryRepository store failed: %s", e)
            raise ValueError("Failed to store memories") from e

    async def update(self, memories: list[Memory]) -> tuple[int, int]:
        try:
            self.logger.info(
                "MemoryRepository update_metadata start memories=%s",
                len(memories),
            )

            success, failed = await self.elasticsearch.bulk_update(
                [self._to_indexed_record(memory) for memory in memories],
                index=MEMORY_INDEX,
            )
            self.logger.info(
                "MemoryRepository update_metadata done success=%s failed=%s",
                success,
                failed,
            )
            return success, failed
        except Exception as e:
            self.logger.exception(
                "MemoryRepository update_metadata failed: %s", e
            )
            raise ValueError("Failed to update metadata") from e

    async def delete(self, ids: list[str]) -> tuple[int, int]:
        try:
            self.logger.info(
                "MemoryRepository delete start ids=%s",
                len(ids),
            )

            success, failed = await self.elasticsearch.bulk_delete(
                ids,
                index=MEMORY_INDEX,
            )
            self.logger.info(
                "MemoryRepository delete done success=%s failed=%s",
                success,
                failed,
            )
            return success, failed
        except Exception as e:
            self.logger.exception("MemoryRepository delete failed: %s", e)
            raise ValueError("Failed to delete memories") from e
