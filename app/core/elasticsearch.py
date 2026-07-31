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

    def _record_actions(
        self, records: Iterable[IndexedRecord], index: IndexName
    ) -> Iterator[_TYPE_BULK_ACTION]:
        for record in records:
            yield {
                "_index": index,
                "_source": self._to_source(record),
            }

    async def index_document(self, record: IndexedRecord, index: str) -> None:
        index = self._resolve_index(index)
        try:
            await self.elasticsearch.index(
                index=index,
                document=self._to_source(record),
            )
            return True
        except Exception as e:
            self.logger.exception("Error indexing document: %s", e)
            raise

    async def bulk_index_documents(
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
                    self.logger.warning("Failed to index document: %s", result)
        except Exception as e:
            self.logger.exception("Error bulk indexing documents: %s", e)
            raise

        self.logger.info(
            "Bulk indexed documents success=%s failed=%s index=%s",
            success,
            failed,
            index,
        )
        return success, failed

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
        """Parse hits returning (doc_id, IndexedRecord) tuples for RRF fusion."""
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

    def _user_filter(self, user_id: str) -> dict:
        return {"term": {"metadata.user_id": user_id}}

    def _document_filter(self, user_id: str, document_id: str) -> dict:
        return {
            "bool": {
                "filter": [
                    {"term": {"metadata.user_id": user_id}},
                    {"term": {"metadata.document_id": document_id}},
                ]
            }
        }

    async def search_vector(
        self,
        user_id: str,
        embedding: list[float],
        index: str,
        *,
        k: int = 10,
        num_candidates: int = 100,
    ) -> list[IndexedRecord]:
        """kNN vector search using dense embeddings, filtered by user_id."""
        index = self._resolve_index(index)
        self.logger.info(
            "ES search_vector start user_id=%s index=%s k=%s num_candidates=%s dims=%s",
            user_id,
            index,
            k,
            num_candidates,
            len(embedding),
        )
        response = await self.elasticsearch.search(
            index=index,
            knn={
                "field": "embedding",
                "query_vector": embedding,
                "k": k,
                "num_candidates": num_candidates,
                "filter": self._user_filter(user_id),
            },
            size=k,
        )
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
    ) -> list[IndexedRecord]:
        """BM25 text search on content field, filtered by user_id."""
        index = self._resolve_index(index)
        self.logger.info(
            "ES search_bm25 start user_id=%s index=%s size=%s query=%r",
            user_id,
            index,
            size,
            query[:120],
        )
        response = await self.elasticsearch.search(
            index=index,
            query={
                "bool": {
                    "must": {"match": {"content": query}},
                    "filter": self._user_filter(user_id),
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
    ) -> list[list[tuple[str, IndexedRecord]]]:
        """Run concurrent BM25 and kNN searches for later fusion.

        Args:
            fetch_size: Docs fetched per branch before fusion (default 50).
            num_candidates: kNN ANN search pool size (default 100).
        """
        index = self._resolve_index(index)
        self.logger.info(
            "ES search_hybrid start user_id=%s index=%s fetch_size=%s "
            "num_candidates=%s dims=%s query=%r",
            user_id,
            index,
            fetch_size,
            num_candidates,
            len(embedding),
            query[:120],
        )
        user_filter = self._user_filter(user_id)

        bm25_coro = self.elasticsearch.search(
            index=index,
            query={
                "bool": {
                    "must": {"match": {"content": query}},
                    "filter": user_filter,
                }
            },
            size=fetch_size,
        )
        knn_coro = self.elasticsearch.search(
            index=index,
            knn={
                "field": "embedding",
                "query_vector": embedding,
                "k": fetch_size,
                "num_candidates": num_candidates,
                "filter": user_filter,
            },
            size=fetch_size,
        )

        results = await asyncio.gather(bm25_coro, knn_coro, return_exceptions=True)
        bm25_response, knn_response = results

        results_lists: list[list[tuple[str, IndexedRecord]]] = []

        if isinstance(bm25_response, Exception):
            self.logger.warning("BM25 search failed: %s", bm25_response)
        else:
            bm25_hits = self._parse_hits_with_ids(bm25_response)
            self.logger.info(
                "ES search_hybrid BM25 branch user_id=%s hits=%s",
                user_id,
                len(bm25_hits),
            )
            results_lists.append(bm25_hits)

        if isinstance(knn_response, Exception):
            self.logger.warning("kNN search failed: %s", knn_response)
        else:
            knn_hits = self._parse_hits_with_ids(knn_response)
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

    async def delete_by_document_id(
        self, user_id: str, document_id: str, index: str
    ) -> int:
        """Delete all chunks for a document_id, filtered by user_id."""
        index = self._resolve_index(index)
        response = await self.elasticsearch.delete_by_query(
            index=index,
            query=self._document_filter(user_id, document_id),
        )
        return response.get("deleted", 0)

    async def delete_all(self, user_id: str, index: str) -> int:
        """Delete all documents for a user."""
        index = self._resolve_index(index)
        response = await self.elasticsearch.delete_by_query(
            index=index,
            query=self._user_filter(user_id),
        )
        return response.get("deleted", 0)

    async def update_by_document_id(
        self,
        user_id: str,
        document_id: str,
        content: str,
        embedding: list[float],
        index: str,
    ) -> int:
        """Update content and embedding for all chunks of a document_id, filtered by user_id."""
        index = self._resolve_index(index)
        response = await self.elasticsearch.update_by_query(
            index=index,
            query=self._document_filter(user_id, document_id),
            script={
                "source": "ctx._source.content = params.content; ctx._source.embedding = params.embedding",
                "params": {"content": content, "embedding": embedding},
            },
        )
        return response.get("updated", 0)
