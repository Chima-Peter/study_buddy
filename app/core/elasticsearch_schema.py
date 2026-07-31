from dataclasses import dataclass
from typing import Literal, TypedDict

IndexName = Literal["documents", "user_memories"]
ALLOWED_INDICES: frozenset[str] = frozenset({"documents", "user_memories"})


class DocumentMetadata(TypedDict, total=False):
    user_id: str
    document_id: str
    chunk_index: int
    chunk_id: str
    page: int
    source: str
    category: str
    name: str


class MemoryMetadata(TypedDict, total=False):
    user_id: str
    memory_id: str
    category: str
    status: str
    importance: float
    confidence: float
    usage_count: int
    last_used_at: str
    source: str
    created_at: str
    updated_at: str
    expires_at: str


IndexMetadata = DocumentMetadata | MemoryMetadata


@dataclass
class IndexedRecord:
    content: str
    metadata: IndexMetadata
    embedding: list[float]


@dataclass
class FusedResult:
    document: IndexedRecord
    score: float
