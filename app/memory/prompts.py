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

    return (
        "Extract durable student memories from this study conversation turn.\n\n"
        "Only store facts that will help personalize future tutoring. "
        "Skip ephemeral chit-chat, one-off questions, and information already "
        "implied by the documents rather than the student.\n\n"
        "Use this taxonomy (category → types):\n"
        f"{taxonomy_description()}\n\n"
        "Rules:\n"
        "1. Each memory must be a single atomic fact\n"
        "2. category and type must form a valid pair from the taxonomy\n"
        "3. Prefer fewer high-quality memories over many weak ones\n"
        "4. If nothing should be stored, return an empty memories list\n"
        "5. Score importance (0-1) from the memory's tutoring value: "
        "high (~0.8-1.0) for goals, constraints, learning needs, or "
        "profile facts that should change how you teach; medium (~0.4-0.7) "
        "for useful preferences or habits; low (~0.1-0.3) for minor details\n"
        "6. Score confidence (0-1) from how clearly the student stated it: "
        "high (~0.8-1.0) for explicit unambiguous claims; medium (~0.4-0.7) "
        "for strong implications; low (~0.1-0.3) for tentative, hedged, or "
        "ambiguous wording\n"
        "7. For temporary memories where the student states an expiry or "
        "duration (e.g. 'until next week', 'for this month', 'tomorrow', "
        "'for 3 days'), set expires_at to a concrete UTC datetime resolved "
        f"from the current time ({reference_utc}). Use end-of-day UTC when "
        "only a day/week/month is given\n"
        "8. Leave expires_at null for lasting preferences, profile facts, and "
        "other memories with no stated time bound\n\n"
        f"Context: {context}\n"
    )


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

    return (
        "Classify each candidate memory against existing memories.\n\n"
        "Use this taxonomy (category → types):\n"
        f"{taxonomy_description()}\n\n"
        "Put every candidate into exactly one of these lists:\n"
        "1. identical: same fact as an existing memory. Set verified=true only "
        "after you confirm they match. Existing is kept; confidence will rise "
        "slightly. Do not invent new content.\n"
        "2. updated: same topic/fact but the candidate revises it. Existing "
        "will be superseded (valid_to=now); the candidate will be stored. Do "
        "not also list that candidate under different.\n"
        "3. different: distinct fact that can coexist. Candidate will be stored.\n"
        "4. contradict: candidate conflicts with an existing memory. Existing "
        "will be archived (valid_to=now); the candidate will be stored.\n\n"
        "Rules:\n"
        "- Use only candidate and existing IDs from the lists below\n"
        "- Do not invent memories, IDs, or facts not shown\n"
        "- If there are no existing memories, put all candidates in different\n"
        "- Prefer identical over updated when nothing material changed\n"
        "- Prefer contradict over different when the facts cannot both be true\n\n"
        f"Candidates:\n{candidate_lines}\n\n"
        f"Existing memories:\n{existing_lines}\n"
    )
