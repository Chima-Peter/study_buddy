from logging import Logger
from app.core.elasticsearch import FusedResult, IndexedDocuments


class Retriever:
    def __init__(self, logger: Logger):
        self.logger = logger

    async def reciprocal_rank_fusion(
        self,
        results_lists: list[list[tuple[str, IndexedDocuments]]],
        *,
        k: int,
        rank_constant: int = 60,
    ) -> list[FusedResult]:
        """
        Local Reciprocal Rank Fusion (RRF), deduped by chunk_id.

        RRF score for chunk c: sum over all retrievers of 1/(rank_constant + rank_i)
        where rank_i is 1-based position in that retriever's results. Falls back to
        the Elasticsearch hit id when metadata.chunk_id is missing.
        """
        scores: dict[str, float] = {}
        docs_by_chunk: dict[str, IndexedDocuments] = {}

        for results in results_lists:
            seen_chunks: set[str] = set()
            for rank, (hit_id, doc) in enumerate(results, start=1):
                chunk_id = doc.metadata.get("chunk_id") or hit_id
                if chunk_id in seen_chunks:
                    continue
                seen_chunks.add(chunk_id)
                scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (
                    rank_constant + rank
                )
                docs_by_chunk.setdefault(chunk_id, doc)

        sorted_ids = sorted(
            scores.keys(), key=lambda d: scores[d], reverse=True
        )
        return [
            FusedResult(document=docs_by_chunk[chunk_id], score=scores[chunk_id])
            for chunk_id in sorted_ids[:k]
        ]
