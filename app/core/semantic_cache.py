"""Redis semantic cache via FT.SEARCH vector KNN (requires Redis 8 / Search)."""

from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np
import redis.asyncio as aioredis
import uuid_utils
from redis.commands.search.field import TagField, TextField, VectorField
from redis.commands.search.index_definition import IndexDefinition, IndexType
from redis.commands.search.query import Query

_TAG_SPECIAL = set("\\,.<>{}[]\"':;!@#$%^&*()-+=~| ")


@dataclass(frozen=True)
class CacheHit:
    query: str
    context: str
    document_id: str
    document_version: str
    chunk_ids: list[str]
    distance: float


@dataclass(frozen=True)
class CacheMiss:
    nearest_distance: float | None = None


class SemanticCache:
    def __init__(
        self,
        redis: aioredis.Redis,
        *,
        index_name: str = "semcache:idx",
        key_prefix: str = "semcache:",
        vector_dim: int = 384,
        distance_threshold: float = 0.3,
        ttl_seconds: int = 3600,
    ) -> None:
        self._redis = redis
        self._index = index_name
        self._prefix = key_prefix
        self._dim = vector_dim
        self._threshold = distance_threshold
        self._ttl = ttl_seconds

    async def create_index(self) -> None:
        schema = (
            TextField("query"),
            TextField("context"),
            TextField("chunk_ids"),
            TagField("document_id"),
            TagField("document_version"),
            VectorField(
                "embedding",
                "HNSW",
                {
                    "TYPE": "FLOAT32",
                    "DIM": self._dim,
                    "DISTANCE_METRIC": "COSINE",
                },
            ),
        )
        try:
            await self._redis.ft(self._index).create_index(
                fields=schema,
                definition=IndexDefinition(
                    prefix=[self._prefix],
                    index_type=IndexType.HASH,
                ),
            )
        except aioredis.ResponseError as exc:
            if "Index already exists" not in str(exc):
                raise

    async def lookup(
        self,
        embedding: np.ndarray,
        document_id: str,
        document_version: str = "v1",
    ) -> CacheHit | CacheMiss:
        """Nearest entry for document; hit only if cosine distance <= threshold."""
        vec = self._vec_bytes(embedding)
        filters = (
            f"(@document_id:{{{self._escape_tag(document_id)}}} "
            f"@document_version:{{{self._escape_tag(document_version)}}})"
        )
        q = (
            Query(f"{filters}=>[KNN 1 @embedding $vec AS distance]")
            .return_fields(
                "query",
                "context",
                "document_id",
                "document_version",
                "chunk_ids",
                "distance",
            )
            .paging(0, 1)
            .dialect(2)
        )
        result = await self._redis.ft(self._index).search(
            q, query_params={"vec": vec}
        )
        if not result.docs:
            return CacheMiss()

        doc = result.docs[0]
        distance = float(doc.distance)
        if distance > self._threshold:
            return CacheMiss(nearest_distance=distance)

        return CacheHit(
            query=_decode(doc.query),
            context=_decode(doc.context),
            document_id=_decode(doc.document_id),
            document_version=_decode(doc.document_version),
            chunk_ids=json.loads(_decode(doc.chunk_ids) or "[]"),
            distance=distance,
        )

    async def put(
        self,
        query: str,
        embedding: np.ndarray,
        context: str,
        document_id: str,
        chunk_ids: list[str],
        document_version: str = "v1",
    ) -> None:
        key = f"{self._prefix}{str(uuid_utils.uuid7())[:12]}"
        await self._redis.hset(
            key,
            mapping={
                "query": query,
                "context": context,
                "document_id": document_id,
                "document_version": document_version,
                "chunk_ids": json.dumps(chunk_ids),
                "embedding": self._vec_bytes(embedding),
            },
        )
        await self._redis.expire(key, self._ttl)

    def _vec_bytes(self, embedding: np.ndarray) -> bytes:
        flat = np.asarray(embedding, dtype=np.float32).reshape(-1)
        if flat.shape != (self._dim,):
            raise ValueError(f"expected dim {self._dim}, got {flat.shape}")
        return flat.tobytes()

    @staticmethod
    def _escape_tag(value: str) -> str:
        return "".join(f"\\{c}" if c in _TAG_SPECIAL else c for c in value)


def _decode(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode()
    return str(value)
