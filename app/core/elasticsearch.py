import asyncio
from collections.abc import Iterable, Iterator
from logging import Logger
from typing import Any, cast

from elasticsearch import AsyncElasticsearch
from elasticsearch.helpers import async_streaming_bulk
from elasticsearch.helpers.actions import _TYPE_BULK_ACTION

from app.core.elasticsearch_schema import (
    ALLOWED_INDICES,
    IndexedRecord,
    IndexMetadata,
    IndexName,
)


class Elasticsearch:
    def __init__(self, elasticsearch: AsyncElasticsearch, logger: Logger):
        self.elasticsearch = elasticsearch
        self.logger = logger
        self.logger.info("Elasticsearch client ready")

    # --- helpers ---

    def _resolve_index(self, index: str) -> IndexName:
        if index not in ALLOWED_INDICES:
            raise ValueError(
                f"Invalid index {index!r}; allowed: {sorted(ALLOWED_INDICES)}"
            )
        return cast(IndexName, index)

    def _to_source(self, record: IndexedRecord) -> dict[str, Any]:
        return {
            "content": record.content,
            "metadata": record.metadata,
            "embedding": record.embedding,
        }

    def _user_filter(self, user_id: str) -> dict:
        return {"term": {"metadata.user_id": user_id}}

    def _metadata_filter(self, user_id: str, **metadata_terms: str) -> dict:
        filters: list[dict] = [{"term": {"metadata.user_id": user_id}}]
        for field, value in metadata_terms.items():
            filters.append({"term": {f"metadata.{field}": value}})
        return {"bool": {"filter": filters}}

    def _parse_hits(self, response: dict) -> list[IndexedRecord]:
        return [
            IndexedRecord(
                content=hit["_source"]["content"],
                metadata=cast(
                    IndexMetadata, hit["_source"].get("metadata", {})
                ),
                embedding=hit["_source"].get("embedding", []),
            )
            for hit in response.get("hits", {}).get("hits", [])
        ]

    def _parse_hits_with_ids(
        self, response: dict
    ) -> list[tuple[str, IndexedRecord]]:
        """Parse hits returning (hit_id, IndexedRecord) tuples for RRF fusion."""
        return [
            (
                hit["_id"],
                IndexedRecord(
                    content=hit["_source"]["content"],
                    metadata=cast(
                        IndexMetadata, hit["_source"].get("metadata", {})
                    ),
                    embedding=hit["_source"].get("embedding", []),
                ),
            )
            for hit in response.get("hits", {}).get("hits", [])
        ]

    def _record_actions(
        self, records: Iterable[IndexedRecord], index: IndexName
    ) -> Iterator[_TYPE_BULK_ACTION]:
        for record in records:
            action: dict[str, Any] = {
                "_index": index,
                "_source": self._to_source(record),
            }
            record_id = record.metadata.get("id")
            if record_id:
                action["_id"] = record_id
            yield action

    def _update_actions(
        self, records: Iterable[IndexedRecord], index: IndexName
    ) -> Iterator[_TYPE_BULK_ACTION]:
        for record in records:
            record_id = record.metadata.get("id")
            if not record_id:
                raise ValueError("metadata.id is required for bulk update")
            yield {
                "_op_type": "update",
                "_index": index,
                "_id": record_id,
                "doc": self._to_source(record),
            }

    def _delete_actions(
        self, ids: Iterable[str], index: IndexName
    ) -> Iterator[_TYPE_BULK_ACTION]:
        for record_id in ids:
            yield {
                "_op_type": "delete",
                "_index": index,
                "_id": record_id,
            }

    # --- write ---

    async def index_record(self, record: IndexedRecord, index: str) -> None:
        index = self._resolve_index(index)
        try:
            kwargs: dict[str, Any] = {
                "index": index,
                "document": self._to_source(record),
            }
            record_id = record.metadata.get("id")
            if record_id:
                kwargs["id"] = record_id
            await self.elasticsearch.index(**kwargs)
        except Exception as e:
            self.logger.exception("Error indexing record: %s", e)
            raise

    async def bulk_index(
        self, records: list[IndexedRecord], index: str
    ) -> tuple[int, int]:
        index = self._resolve_index(index)
        success = 0
        failed = 0
        actions: Iterable[_TYPE_BULK_ACTION] = self._record_actions(records, index)

        try:
            async for ok, result in async_streaming_bulk(
                self.elasticsearch,
                actions,
                max_retries=3,
                chunk_size=100,
                max_chunk_bytes=1024 * 1024 * 10,
            ):
                if ok:
                    success += 1
                else:
                    failed += 1
                    self.logger.warning("Failed to index record: %s", result)
        except Exception as e:
            self.logger.exception("Error bulk indexing records: %s", e)
            raise

        self.logger.info(
            "Bulk indexed records success=%s failed=%s index=%s",
            success,
            failed,
            index,
        )
        return success, failed

    # --- update ---

    async def bulk_update(
        self, records: list[IndexedRecord], index: str
    ) -> tuple[int, int]:
        """Bulk-update records by metadata.id (used as the Elasticsearch _id)."""
        index = self._resolve_index(index)
        success = 0
        failed = 0
        actions: Iterable[_TYPE_BULK_ACTION] = self._update_actions(records, index)

        try:
            async for ok, result in async_streaming_bulk(
                self.elasticsearch,
                actions,
                max_retries=3,
                chunk_size=100,
                max_chunk_bytes=1024 * 1024 * 10,
                raise_on_error=False,
            ):
                if ok:
                    success += 1
                else:
                    failed += 1
                    self.logger.warning("Failed to update record: %s", result)
        except Exception:
            self.logger.exception("Error bulk updating records: %s")
            raise

        self.logger.info(
            "Bulk updated records success=%s failed=%s index=%s",
            success,
            failed,
            index,
        )
        return success, failed

    async def update_by_metadata(
        self,
        user_id: str,
        content: str,
        embedding: list[float],
        index: str,
        metadata: dict[str, Any],
        **metadata_terms: str,
    ) -> int:
        """Update content, embedding, and metadata for records matching terms."""
        if not metadata_terms:
            raise ValueError("At least one metadata term is required")
        index = self._resolve_index(index)
        response = await self.elasticsearch.update_by_query(
            index=index,
            query=self._metadata_filter(user_id, **metadata_terms),
            script={
                "source": (
                    "ctx._source.content = params.content; "
                    "ctx._source.embedding = params.embedding; "
                    "ctx._source.metadata = params.metadata"
                ),
                "params": {
                    "content": content,
                    "embedding": embedding,
                    "metadata": metadata,
                },
            },
        )
        return response.get("updated", 0)

    # --- search ---

    def _search_filter(
        self, user_id: str, **metadata_terms: str
    ) -> dict:
        if metadata_terms:
            return self._metadata_filter(user_id, **metadata_terms)
        return self._user_filter(user_id)

    def _records_for_fusion(
        self, records: list[IndexedRecord]
    ) -> list[tuple[str, IndexedRecord]]:
        return [
            (str(record.metadata.get("id") or ""), record) for record in records
        ]

    async def search_vector(
        self,
        user_id: str,
        embedding: list[float],
        index: str,
        *,
        k: int = 10,
        num_candidates: int = 100,
        min_score: float | None = None,
        **metadata_terms: str,
    ) -> list[IndexedRecord]:
        """kNN vector search using dense embeddings, filtered by user/metadata."""
        index = self._resolve_index(index)
        self.logger.info(
            "ES search_vector start user_id=%s index=%s k=%s "
            "num_candidates=%s min_score=%s dims=%s metadata_terms=%s",
            user_id,
            index,
            k,
            num_candidates,
            min_score,
            len(embedding),
            metadata_terms,
        )
        request: dict[str, Any] = {
            "index": index,
            "knn": {
                "field": "embedding",
                "query_vector": embedding,
                "k": k,
                "num_candidates": num_candidates,
                "filter": self._search_filter(user_id, **metadata_terms),
            },
            "size": k,
        }
        if min_score is not None:
            request["min_score"] = min_score
        response = await self.elasticsearch.search(**request)
        hits = self._parse_hits(response)
        self.logger.info(
            "ES search_vector done user_id=%s index=%s hits=%s",
            user_id,
            index,
            len(hits),
        )
        return hits

    async def search_bm25(
        self,
        user_id: str,
        query: str,
        index: str,
        *,
        size: int = 10,
        **metadata_terms: str,
    ) -> list[IndexedRecord]:
        """BM25 text search on content field, filtered by user/metadata."""
        index = self._resolve_index(index)
        self.logger.info(
            "ES search_bm25 start user_id=%s index=%s size=%s "
            "metadata_terms=%s query=%r",
            user_id,
            index,
            size,
            metadata_terms,
            query[:120],
        )
        response = await self.elasticsearch.search(
            index=index,
            query={
                "bool": {
                    "must": {"match": {"content": query}},
                    "filter": self._search_filter(user_id, **metadata_terms),
                }
            },
            size=size,
        )
        hits = self._parse_hits(response)
        self.logger.info(
            "ES search_bm25 done user_id=%s index=%s hits=%s",
            user_id,
            index,
            len(hits),
        )
        return hits

    async def search_hybrid(
        self,
        user_id: str,
        query: str,
        embedding: list[float],
        index: str,
        *,
        fetch_size: int = 50,
        num_candidates: int = 100,
        **metadata_terms: str,
    ) -> list[list[tuple[str, IndexedRecord]]]:
        """Run concurrent BM25 and kNN searches for later fusion.

        Args:
            fetch_size: Records fetched per branch before fusion (default 50).
            num_candidates: kNN ANN search pool size (default 100).
            **metadata_terms: Optional metadata term filters (e.g. category, status).
        """
        self.logger.info(
            "ES search_hybrid start user_id=%s index=%s fetch_size=%s "
            "num_candidates=%s dims=%s metadata_terms=%s query=%r",
            user_id,
            index,
            fetch_size,
            num_candidates,
            len(embedding),
            metadata_terms,
            query[:120],
        )

        results = await asyncio.gather(
            self.search_bm25(
                user_id,
                query,
                index,
                size=fetch_size,
                **metadata_terms,
            ),
            self.search_vector(
                user_id,
                embedding,
                index,
                k=fetch_size,
                num_candidates=num_candidates,
                **metadata_terms,
            ),
            return_exceptions=True,
        )
        bm25_result, knn_result = results

        results_lists: list[list[tuple[str, IndexedRecord]]] = []

        if isinstance(bm25_result, Exception):
            self.logger.warning("BM25 search failed: %s", bm25_result)
        else:
            bm25_hits = self._records_for_fusion(bm25_result)
            self.logger.info(
                "ES search_hybrid BM25 branch user_id=%s hits=%s",
                user_id,
                len(bm25_hits),
            )
            results_lists.append(bm25_hits)

        if isinstance(knn_result, Exception):
            self.logger.warning("kNN search failed: %s", knn_result)
        else:
            knn_hits = self._records_for_fusion(knn_result)
            self.logger.info(
                "ES search_hybrid kNN branch user_id=%s hits=%s",
                user_id,
                len(knn_hits),
            )
            results_lists.append(knn_hits)

        if not results_lists:
            self.logger.error("Both BM25 and kNN searches failed")
            return []

        self.logger.info(
            "ES search_hybrid done user_id=%s index=%s results_lists=%s",
            user_id,
            index,
            len(results_lists),
        )
        return results_lists

    async def search_by_metadata(
        self, user_id: str, index: str, **metadata_terms: str
    ) -> list[IndexedRecord]:
        """Search for records matching user_id and metadata term filters."""
        index = self._resolve_index(index)
        self.logger.info(
            "ES search_by_metadata start user_id=%s index=%s metadata_terms=%s",
            user_id,
            index,
            metadata_terms,
        )
        response = await self.elasticsearch.search(
            index=index,
            query=self._metadata_filter(user_id, **metadata_terms),
            size=1000,
        )
        hits = self._parse_hits(response)
        self.logger.info(
            "ES search_by_metadata done user_id=%s index=%s hits=%s",
            user_id,
            index,
            len(hits),
        )
        return hits

    # --- delete ---

    async def bulk_delete(
        self, ids: list[str], index: str
    ) -> tuple[int, int]:
        """Bulk-delete records by Elasticsearch _id (same as metadata.id)."""
        if not ids:
            return 0, 0
        index = self._resolve_index(index)
        success = 0
        failed = 0
        actions: Iterable[_TYPE_BULK_ACTION] = self._delete_actions(ids, index)

        try:
            async for ok, result in async_streaming_bulk(
                self.elasticsearch,
                actions,
                max_retries=3,
                chunk_size=100,
                max_chunk_bytes=1024 * 1024 * 10,
            ):
                if ok:
                    success += 1
                else:
                    failed += 1
                    self.logger.warning("Failed to delete record: %s", result)
        except Exception as e:
            self.logger.exception("Error bulk deleting records: %s", e)
            raise

        self.logger.info(
            "Bulk deleted records success=%s failed=%s index=%s",
            success,
            failed,
            index,
        )
        return success, failed

    async def delete_by_metadata(
        self, user_id: str, index: str, **metadata_terms: str
    ) -> int:
        """Delete records matching user_id and metadata term filters."""
        if not metadata_terms:
            raise ValueError("At least one metadata term is required")
        index = self._resolve_index(index)
        response = await self.elasticsearch.delete_by_query(
            index=index,
            query=self._metadata_filter(user_id, **metadata_terms),
        )
        return response.get("deleted", 0)

    async def delete_by_user(self, user_id: str, index: str) -> int:
        """Delete all records for a user in the given index."""
        index = self._resolve_index(index)
        response = await self.elasticsearch.delete_by_query(
            index=index,
            query=self._user_filter(user_id),
        )
        return response.get("deleted", 0)
