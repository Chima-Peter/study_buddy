import asyncio
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from logging import Logger
from typing import Any

from elasticsearch import AsyncElasticsearch
from elasticsearch.helpers import async_streaming_bulk
from elasticsearch.helpers.actions import _TYPE_BULK_ACTION


@dataclass
class IndexedDocuments:
    content: str
    metadata: dict[str, Any]
    embedding: list[float]


@dataclass
class FusedResult:
    document: IndexedDocuments
    score: float


class Elasticsearch:
    def __init__(self, elasticsearch: AsyncElasticsearch, logger: Logger):
        self.elasticsearch = elasticsearch
        self.logger = logger
        self.logger.info("Elasticsearch client ready")

    def _to_source(self, document: IndexedDocuments) -> dict[str, Any]:
        return {
            "content": document.content,
            "metadata": document.metadata,
            "embedding": document.embedding,
        }

    def _document_actions(
        self, documents: Iterable[IndexedDocuments]
    ) -> Iterator[_TYPE_BULK_ACTION]:
        for document in documents:
            yield {
                "_index": "documents",
                "_source": self._to_source(document),
            }

    async def index_document(self, document: IndexedDocuments) -> None:
        try:
            await self.elasticsearch.index(
                index="documents",
                document=self._to_source(document),
            )
            return True
        except Exception as e:
            self.logger.exception("Error indexing document: %s", e)
            raise

    async def bulk_index_documents(
        self, documents: list[IndexedDocuments]
    ) -> tuple[int, int]:
        success = 0
        failed = 0
        actions: Iterable[_TYPE_BULK_ACTION] = self._document_actions(
            documents)

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
            "Bulk indexed documents success=%s failed=%s", success, failed
        )
        return success, failed

    def _parse_hits(self, response: dict) -> list[IndexedDocuments]:
        return [
            IndexedDocuments(
                content=hit["_source"]["content"],
                metadata=hit["_source"].get("metadata", {}),
                embedding=hit["_source"].get("embedding", []),
            )
            for hit in response.get("hits", {}).get("hits", [])
        ]

    def _parse_hits_with_ids(
        self, response: dict
    ) -> list[tuple[str, IndexedDocuments]]:
        """Parse hits returning (doc_id, IndexedDocuments) tuples for RRF fusion."""
        return [
            (
                hit["_id"],
                IndexedDocuments(
                    content=hit["_source"]["content"],
                    metadata=hit["_source"].get("metadata", {}),
                    embedding=hit["_source"].get("embedding", []),
                ),
            )
            for hit in response.get("hits", {}).get("hits", [])
        ]

    def _rrf_fuse(
        self,
        results_lists: list[list[tuple[str, IndexedDocuments]]],
        *,
        k: int,
        rank_constant: int = 60,
    ) -> list[FusedResult]:
        """
        Local Reciprocal Rank Fusion (RRF).

        RRF score for document d: sum over all retrievers of 1/(rank_constant + rank_i)
        where rank_i is 1-based position in that retriever's results.
        """
        scores: dict[str, float] = {}
        docs_by_id: dict[str, IndexedDocuments] = {}

        for results in results_lists:
            for rank, (doc_id, doc) in enumerate(results, start=1):
                scores[doc_id] = scores.get(
                    doc_id, 0.0) + 1.0 / (rank_constant + rank)
                docs_by_id[doc_id] = doc

        sorted_ids = sorted(
            scores.keys(), key=lambda d: scores[d], reverse=True)
        return [
            FusedResult(document=docs_by_id[doc_id], score=scores[doc_id])
            for doc_id in sorted_ids[:k]
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
        *,
        k: int = 10,
        num_candidates: int = 100,
    ) -> list[IndexedDocuments]:
        """kNN vector search using dense embeddings, filtered by user_id."""
        response = await self.elasticsearch.search(
            index="documents",
            knn={
                "field": "embedding",
                "query_vector": embedding,
                "k": k,
                "num_candidates": num_candidates,
                "filter": self._user_filter(user_id),
            },
            size=k,
        )
        return self._parse_hits(response)

    async def search_bm25(
        self,
        user_id: str,
        query: str,
        *,
        size: int = 10,
    ) -> list[IndexedDocuments]:
        """BM25 text search on content field, filtered by user_id."""
        response = await self.elasticsearch.search(
            index="documents",
            query={
                "bool": {
                    "must": {"match": {"content": query}},
                    "filter": self._user_filter(user_id),
                }
            },
            size=size,
        )
        return self._parse_hits(response)

    async def search_hybrid(
        self,
        user_id: str,
        query: str,
        embedding: list[float],
        *,
        k: int = 10,
        window_size: int = 100,
        rank_constant: int = 60,
    ) -> list[FusedResult]:
        """Hybrid search: concurrent BM25 + kNN with local RRF fusion."""
        user_filter = self._user_filter(user_id)

        bm25_coro = self.elasticsearch.search(
            index="documents",
            query={
                "bool": {
                    "must": {"match": {"content": query}},
                    "filter": user_filter,
                }
            },
            size=window_size,
        )
        knn_coro = self.elasticsearch.search(
            index="documents",
            knn={
                "field": "embedding",
                "query_vector": embedding,
                "k": window_size,
                "num_candidates": window_size,
                "filter": user_filter,
            },
            size=window_size,
        )

        results = await asyncio.gather(bm25_coro, knn_coro, return_exceptions=True)
        bm25_response, knn_response = results

        results_lists: list[list[tuple[str, IndexedDocuments]]] = []

        if isinstance(bm25_response, Exception):
            self.logger.warning("BM25 search failed: %s", bm25_response)
        else:
            results_lists.append(self._parse_hits_with_ids(bm25_response))

        if isinstance(knn_response, Exception):
            self.logger.warning("kNN search failed: %s", knn_response)
        else:
            results_lists.append(self._parse_hits_with_ids(knn_response))

        if not results_lists:
            self.logger.error("Both BM25 and kNN searches failed")
            return []

        return self._rrf_fuse(results_lists, k=k, rank_constant=rank_constant)

    async def delete_by_document_id(self, user_id: str, document_id: str) -> int:
        """Delete all chunks for a document_id, filtered by user_id."""
        response = await self.elasticsearch.delete_by_query(
            index="documents",
            query=self._document_filter(user_id, document_id),
        )
        return response.get("deleted", 0)

    async def delete_all(self, user_id: str) -> int:
        """Delete all documents for a user."""
        response = await self.elasticsearch.delete_by_query(
            index="documents",
            query=self._user_filter(user_id),
        )
        return response.get("deleted", 0)

    async def update_by_document_id(
        self,
        user_id: str,
        document_id: str,
        content: str,
        embedding: list[float],
    ) -> int:
        """Update content and embedding for all chunks of a document_id, filtered by user_id."""
        response = await self.elasticsearch.update_by_query(
            index="documents",
            query=self._document_filter(user_id, document_id),
            script={
                "source": "ctx._source.content = params.content; ctx._source.embedding = params.embedding",
                "params": {"content": content, "embedding": embedding},
            },
        )
        return response.get("updated", 0)
