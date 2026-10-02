from dataclasses import dataclass
from typing import Literal, TypedDict

IndexName = Literal["documents", "user_memories"]
ALLOWED_INDICES: frozenset[str] = frozenset({"documents", "user_memories"})


class DocumentMetadata(TypedDict, total=False):
    id: str
    user_id: str
    document_id: str
    chunk_index: int
    page: int
    source: str
    category: str
    name: str
    chapter: str
    chapter_key: str
    chapter_number: int


class MemoryMetadata(TypedDict, total=False):
    id: str
    user_id: str
    category: str
    document_id: str
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
