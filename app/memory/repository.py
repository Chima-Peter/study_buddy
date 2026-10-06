import base64
import json
from logging import Logger
from typing import Any, cast

from app.core.elasticsearch import Elasticsearch
from app.core.elasticsearch_schema import IndexedRecord, MemoryMetadata
from app.core.retriever import Retriever
from app.memory.schema import (
    DEFAULT_LIST_LIMIT,
    MAX_LIST_LIMIT,
    MEMORY_INDEX,
    SEARCH_TOP_K,
    Memory,
    MemorySearch,
)



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

    @staticmethod
    def _encode_cursor(sort_values: list[Any]) -> str:
        raw = json.dumps(sort_values, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    @staticmethod
    def _decode_cursor(cursor: str) -> list[Any]:
        padding = "=" * (-len(cursor) % 4)
        try:
            decoded = json.loads(base64.urlsafe_b64decode(cursor + padding))
        except (ValueError, json.JSONDecodeError) as e:
            raise ValueError("Invalid cursor") from e
        if not isinstance(decoded, list) or not decoded:
            raise ValueError("Invalid cursor")
        return decoded

    async def retrieve(self, search: MemorySearch) -> list[Memory]:
        try:
            self.logger.info(
                "MemoryRepository search start user_id=%s "
                "category=%s document_id=%s",
                search.user_id,
                search.category,
                search.document_id,
            )

            results_lists = await self.elasticsearch.search_hybrid(
                search.user_id,
                search.content,
                search.embedding,
                index=MEMORY_INDEX,
                min_score=None,
                category=search.category,
                document_id=search.document_id,
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

    async def list_by_user(
        self,
        user_id: str,
        *,
        limit: int = DEFAULT_LIST_LIMIT,
        cursor: str | None = None,
    ) -> tuple[list[Memory], str | None, bool]:
        limit = min(max(limit, 1), MAX_LIST_LIMIT)
        search_after = self._decode_cursor(cursor) if cursor else None

        try:
            self.logger.info(
                "MemoryRepository list start user_id=%s limit=%s has_cursor=%s",
                user_id,
                limit,
                cursor is not None,
            )
            records, next_sort, has_more = await self.elasticsearch.list_by_user(
                user_id,
                MEMORY_INDEX,
                limit=limit,
                search_after=search_after,
            )
            memories = [self._from_indexed_record(record) for record in records]
            next_cursor = (
                self._encode_cursor(next_sort)
                if has_more and next_sort is not None
                else None
            )
            self.logger.info(
                "MemoryRepository list done user_id=%s count=%s has_more=%s",
                user_id,
                len(memories),
                has_more,
            )
            return memories, next_cursor, has_more
        except ValueError:
            raise
        except Exception as e:
            self.logger.exception("MemoryRepository list failed: %s", e)
            raise ValueError("Failed to list memories") from e

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
