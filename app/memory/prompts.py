from datetime import datetime, timezone

from app.memory.schema import Memory


def memory_extraction_prompt(
    context: str,
    *,
    known_memories: list[str] | None = None,
    now: datetime | None = None,
) -> str:
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    reference_utc = reference.astimezone(timezone.utc).isoformat()

    known_block = "\n".join(
        f"- {memory}" for memory in (known_memories or [])
    ) or "- (none)"

    return f"""Extract multiple NEW durable facts about the user for future tutoring.

Format: Complete sentence starting with "The user" or "The user's".
Good: "The user attends University of Lagos.", "The user prefers visual explanations."
Bad: "Peter likes math" (missing "The user"), "The user's name is Peter" (never store user's name).

Already known memories (DO NOT re-extract these or paraphrases of them):
{known_block}

NEVER extract:
- Anything listed under already known memories above
- The user's own name (already on their profile). Only extract other people's names when relevant.
- Facts the assistant already recalled/mentioned in the conversation (already stored)
- Facts from assistant responses that came from memory retrieval

Only extract NEW information from the user's messages that is not already known.

IMPORTANT - Negations and changes:
When user says "I no longer want X" or "I don't like X anymore" or "I prefer Y now instead of X":
- Extract BOTH facts separately:
  1. "The user is no longer interested in X." (the negation)
  2. "The user is interested in Y." (the new preference)
- This ensures old contradicting memories get archived.

Categories (pick exactly one):
- personal: everything OUTSIDE school/studying (gender, job, hobbies, family, life goals, constraints)
- study: everything ABOUT school/studying (topics, courses, exams, strengths, weaknesses, learning style)

Scoring (0.0-1.0):
- importance: 0.8+ core facts, 0.5-0.7 useful preferences, <0.5 minor details
- confidence: 0.8+ explicit statement, 0.5-0.7 implied, <0.5 uncertain

Rules:
1. One atomic fact per memory; return [] if nothing new worth storing
2. Skip facts already listed as known or already recalled in the conversation
3. When uncertain, skip rather than guess
4. Set expires_at only if student gives a time bound; otherwise null

Reference time: {reference_utc}

Conversation:
{context}""".strip()


def memory_deduplication_prompt(
    candidates: list[Memory],
    related_by_candidate: dict[str, list[Memory]],
) -> str:
    blocks: list[str] = []
    for candidate in candidates:
        related = related_by_candidate.get(candidate.id) or []
        related_lines = "\n".join(
            f"  - id={m.id}: {m.content} (category={m.category}, "
            f"status={m.status}, confidence={m.confidence})"
            for m in related
        ) or "  - (none)"
        blocks.append(
            f"Candidate id={candidate.id}:\n"
            f"  content: {candidate.content}\n"
            f"  category: {candidate.category}\n"
            f"  Related existing:\n{related_lines}"
        )
    candidate_blocks = "\n\n".join(blocks) or "(none)"

    return f"""Classify each candidate against ONLY its own Related existing list.
Put every candidate in exactly one relation list.

Relations:
- identical: Same fact as a related existing. Set verified=true. Existing is kept.
- updated: Revises a related existing with more detail. Existing is superseded; candidate is stored.
- different: New fact that can coexist with its related existing (or related is empty). Candidate is stored.
- contradict: Conflicts with a related existing (can't both be true). Existing is archived; candidate is stored.

CRITICAL for contradict:
- "interested in X" vs "no longer interested in X" → CONTRADICT (negation)
- "likes X" vs "dislikes X" → CONTRADICT
- "prefers X" vs "prefers Y" (when mutually exclusive on the same topic) → CONTRADICT
- Any fact and its negation → CONTRADICT

Rules:
1. Use only IDs from that candidate's Related existing list - do not invent IDs
2. Do not compare a candidate against another candidate's related list
3. If a candidate's Related existing is empty, put it in "different"
4. Prefer "identical" over "updated" when nothing material changed
5. ALWAYS use "contradict" when candidate negates or reverses a related existing fact

{candidate_blocks}""".strip()
