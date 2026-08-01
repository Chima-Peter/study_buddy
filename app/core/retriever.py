from logging import Logger

from app.core.elasticsearch_schema import FusedResult, IndexMetadata, IndexedRecord


class Retriever:
    def __init__(self, logger: Logger):
        self.logger = logger

    def _record_id(self, hit_id: str, metadata: IndexMetadata) -> str:
        return metadata.get("id") or hit_id

    async def reciprocal_rank_fusion(
        self,
        results_lists: list[list[tuple[str, IndexedRecord]]],
        *,
        k: int,
        rank_constant: int = 60,
    ) -> list[FusedResult]:
        """
        Local Reciprocal Rank Fusion (RRF), deduped by record id.

        RRF score for record r: sum over all retrievers of 1/(rank_constant + rank_i)
        where rank_i is 1-based position in that retriever's results. Uses
        metadata.id when present, otherwise the Elasticsearch hit id.
        """
        scores: dict[str, float] = {}
        docs_by_id: dict[str, IndexedRecord] = {}

        for results in results_lists:
            seen_ids: set[str] = set()
            for rank, (hit_id, doc) in enumerate(results, start=1):
                record_id = self._record_id(hit_id, doc.metadata)
                if record_id in seen_ids:
                    continue
                seen_ids.add(record_id)
                scores[record_id] = scores.get(record_id, 0.0) + 1.0 / (
                    rank_constant + rank
                )
                docs_by_id.setdefault(record_id, doc)

        sorted_ids = sorted(
            scores.keys(), key=lambda d: scores[d], reverse=True
        )
        return [
            FusedResult(document=docs_by_id[record_id], score=scores[record_id])
            for record_id in sorted_ids[:k]
        ]
