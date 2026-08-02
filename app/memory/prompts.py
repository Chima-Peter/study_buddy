from datetime import datetime, timezone

from app.memory.schema import Memory


def memory_extraction_prompt(
    context: str,
    *,
    now: datetime | None = None,
) -> str:
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    reference_utc = reference.astimezone(timezone.utc).isoformat()

    return f"""Extract NEW durable facts about the user for future tutoring.

Format: Complete sentence starting with "The user" or "The user's".
Good: "The user attends University of Lagos.", "The user prefers visual explanations."
Bad: "Peter likes math" (missing "The user"), "The user's name is Peter" (never store user's name).

NEVER extract:
- The user's own name (already on their profile). Only extract other people's names when relevant.
- Facts the assistant already recalled/mentioned in the conversation (already stored)
- Facts from assistant responses that came from memory retrieval

Only extract NEW information from the user's messages that is not already known.

Categories (pick exactly one):
- personal: gender, schedule, life goals, constraints, other people's names
- academic: university, subjects, exams, study resources
- learning: strengths, weaknesses, learning style, pace, topic mastery

Scoring (0.0-1.0):
- importance: 0.8+ core facts, 0.5-0.7 useful preferences, <0.5 minor details
- confidence: 0.8+ explicit statement, 0.5-0.7 implied, <0.5 uncertain

Rules:
1. One atomic fact per memory; return [] if nothing new worth storing
2. Skip facts the assistant already knows/recalls in the conversation
3. On corrections, extract only the corrected fact
4. When uncertain, skip rather than guess
5. Set expires_at only if student gives a time bound; otherwise null

Reference time: {reference_utc}

Conversation:
{context}""".strip()


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

    return f"""Classify each candidate memory against existing memories. Put every candidate in exactly one list.

Relations:
- identical: Same fact as existing. Set verified=true after confirming. Existing is kept.
- updated: Revises an existing fact. Existing is superseded; candidate is stored.
- different: New fact that can coexist with existing. Candidate is stored.
- contradict: Conflicts with existing (can't both be true). Existing is archived; candidate is stored.

Rules:
1. Use only IDs from the lists below - do not invent IDs
2. If no existing memories, put all candidates in "different"
3. Prefer "identical" over "updated" when nothing material changed
4. Prefer "contradict" over "different" when both facts cannot be true simultaneously

Candidates:
{candidate_lines}

Existing:
{existing_lines}""".strip()
