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
Extract durable facts about the user that will help future tutoring.

Write each memory as one complete, self-contained sentence.
Always start with "The user" or "The user's".
Include the user's name in the sentence when it is known.

Good:
- The user's name is Peter.
- The user's gender is male.
- The user Peter likes CSC.
- The user Peter attends University of Lagos.
- The user Peter prefers short worked examples.

Bad:
- Peter likes CSC
- likes CSC
- CSC
- Prefers short examples

Keep: name, gender, preferences, goals, university/subjects/exams, strengths/weaknesses, learning style, habits, constraints, mastery/milestones.
Skip: chit-chat, one-off requests, assistant replies, document-only facts, speculation.

Rules:
1. One atomic fact per memory. Prefer fewer high-quality memories; return [] if none.
2. On corrections, extract only the new fact.
3. When uncertain, skip.
4. Choose exactly one category using the conditions below. Be exact.
   - personal = identity, schedule, life goals, constraints
   - academic = school, subjects, exams, resources
   - learning = strengths, weaknesses, style, pace, mastery, teaching fit

Scoring (0.0–1.0):
- importance: high=changes tutoring; medium=useful personalization; low=minor detail.
- confidence: high=explicit; medium=strongly implied; low=ambiguous.

Set expires_at only when the student marks it temporary; else null.
Resolve relative times from {reference_utc} (UTC).

Categories:
{taxonomy_description()}

Conversation:
{context}
""".strip()


def memory_deduplication_prompt(
    candidates: list[Memory],
    existing: list[Memory],
) -> str:
    candidate_lines = "\n".join(
        f"- id={c.id}: {c.content} (category={c.category}, "
        f"importance={c.importance}, confidence={c.confidence})"
        for c in candidates
    ) or "- (none)"
    existing_lines = "\n".join(
        f"- id={m.id}: {m.content} (category={m.category}, "
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

Categories:
{taxonomy_description()}

Candidates:
{candidate_lines}

Existing:
{existing_lines}
""".strip()
