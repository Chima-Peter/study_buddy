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


class Elasticsearch:
    def __init__(self, elasticsearch: AsyncElasticsearch, logger: Logger):
        self.elasticsearch = elasticsearch
        self.logger = logger

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
                chunk_size=len(documents),
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

    def _user_filter(self, user_id: str) -> dict:
        return {"term": {"metadata.user_id.keyword": user_id}}

    def _document_filter(self, user_id: str, document_id: str) -> dict:
        return {
            "bool": {
                "filter": [
                    {"term": {"metadata.user_id.keyword": user_id}},
                    {"term": {"metadata.document_id.keyword": document_id}},
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
    ) -> list[IndexedDocuments]:
        """Hybrid search using RRF, filtered by user_id."""
        user_filter = self._user_filter(user_id)
        response = await self.elasticsearch.search(
            index="documents",
            retriever={
                "rrf": {
                    "retrievers": [
                        {
                            "standard": {
                                "query": {
                                    "bool": {
                                        "must": {"match": {"content": query}},
                                        "filter": user_filter,
                                    }
                                }
                            }
                        },
                        {
                            "knn": {
                                "field": "embedding",
                                "query_vector": embedding,
                                "k": window_size,
                                "num_candidates": window_size,
                                "filter": user_filter,
                            }
                        },
                    ],
                    "rank_constant": rank_constant,
                    "rank_window_size": window_size,
                }
            },
            size=k,
        )
        return self._parse_hits(response)

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
