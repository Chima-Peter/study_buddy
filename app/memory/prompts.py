from datetime import datetime, timezone

from app.memory.schema import Memory, taxonomy_description


def memory_extraction_prompt(
    context: str,
    *,
    now: datetime | None = None,
) -> str:
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    reference_utc = reference.astimezone(timezone.utc).isoformat()

    return f"""
        Extract durable student memories that will improve future tutoring.

        Keep: profile (especially name and gender — always extract when stated), preferences, strengths/weaknesses, learning style, goals, exams, schedule, habits, constraints.
        Skip: chit-chat, one-off requests, assistant replies, document-only facts, speculation.

        Rules:
        1. Student facts only; one atomic fact per memory; concise third-person statements.
        2. Prefer fewer high-quality memories; return [] if none.
        3. On corrections, extract only the new fact.
        4. When uncertain, skip. Use only valid category/type pairs from the taxonomy.

        Scoring (0.0–1.0):
        - importance: high=changes tutoring; medium=useful personalization; low=minor detail.
        - confidence: high=explicit; medium=strongly implied; low=ambiguous.

        Set expires_at only when the student marks it temporary; else null.
        Resolve relative times from {reference_utc} (UTC).

        Taxonomy:
        {taxonomy_description()}

        Conversation:
        {context}
    """.strip()


def memory_deduplication_prompt(
    candidates: list[Memory],
    existing: list[Memory],
) -> str:
    candidate_lines = "\n".join(
        f"- id={c.id}: {c.content} (category={c.category}, type={c.type}, "
        f"importance={c.importance}, confidence={c.confidence})"
        for c in candidates
    ) or "- (none)"
    existing_lines = "\n".join(
        f"- id={m.id}: {m.content} (category={m.category}, type={m.type}, "
        f"status={m.status}, confidence={m.confidence})"
        for m in existing
    ) or "- (none)"

    return f"""
Classify each candidate against existing memories. Put every candidate in exactly one list.

Relations:
- identical: same fact; set verified=true only after confirming. Existing kept (confidence rises).
- updated: same topic revised; existing superseded; candidate stored.
- different: distinct fact that can coexist; candidate stored.
- contradict: conflicts with existing; existing archived; candidate stored.

Rules:
1. Use only IDs from the lists below; invent nothing.
2. If no existing memories, put all candidates in different.
3. Prefer identical over updated when nothing material changed.
4. Prefer contradict over different when both cannot be true.

Taxonomy:
{taxonomy_description()}

Candidates:
{candidate_lines}

Existing:
{existing_lines}
""".strip()
