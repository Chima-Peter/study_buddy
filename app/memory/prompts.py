from datetime import datetime, timezone

from app.memory.schema import Memory, taxonomy_description


def memory_search_query_prompt(
    context: str,
    *,
    known_memories: list[str] | None = None,
    document_id: str | None = None,
    now: datetime | None = None,
) -> str:
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    reference_utc = reference.astimezone(timezone.utc).isoformat()

    known_block = "\n".join(
        f"- {memory}" for memory in (known_memories or [])
    ) or "- (none)"
    active_document = document_id or "null"

    return f"""Identify search queries for retrieving existing memories that may
be affected by NEW durable information in the user's messages.

Your job is ONLY to generate retrieval queries. Do not decide whether an
existing memory should be patched, removed, or kept. A later step will make
that decision.

Generate a query when the conversation contains a new, changed, contradicted,
completed, abandoned, or otherwise updated durable fact about the user.

## What makes a good search query

Each query must be a partial statement beginning with "The user", written in
the style of stored memories.

Good:
- "The user prefers visual explanations"
- "The user is learning binary trees"
- "The user struggles with recursion"
- "The user is preparing for IELTS"
- "The user is interested in fintech"

Bad:
- "learning style?"
- "Does the user like Python?"
- "Peter likes math"
- "What memories are related to IELTS?"

Search queries should represent the UNDERLYING FACT or TOPIC that may have
changed, not merely repeat the user's exact wording.

For example:

Existing memory might say:
"The user is preparing for the IELTS exam."

New conversation:
"I took the IELTS yesterday."

A good search query is:
"The user is preparing for the IELTS exam"

or:
"The user has taken the IELTS exam"

Both target the same underlying topic.

When a new fact represents progress, revision, contradiction, or replacement
of an existing fact, search for the broader underlying topic so that the
existing memory can be retrieved.

## Search broadly enough to catch revisions

Do not require the new fact and existing memory to use the same wording.

Examples:

- "I finally understand recursion"
  → search for recursion-related learning difficulty/progress.

- "I finished binary trees"
  → search for binary trees and related learning progress.

- "I prefer Go now instead of Python"
  → search for programming-language preferences involving Go and Python.

- "I no longer want to study in Canada"
  → search for memories about the user's study-abroad/Canada preference or plan.

- "My exam is tomorrow"
  → search for the relevant exam and preparation/status memory.

The purpose is to retrieve candidate memories that might represent the same
underlying fact, even when the wording differs.

## Categories

Optionally include a category when it clearly helps narrow retrieval:

{taxonomy_description()}

Use the category that best describes the underlying memory being searched for.

Do not force a category when the fact could reasonably belong to multiple
categories or when omitting it improves recall.

## Document scope

Active document_id: {active_document}

Use document_id when searching for document-scoped facts in:
- learning_preferences
- academic_progress
- tests_exams

For global facts or other categories, do not require document_id.

## Already known this turn

{known_block}

These facts are already known during this turn, but STILL generate a query
when the user's messages revise, contradict, progress, replace, or otherwise
change one of them.

Do not generate a query merely because an unchanged known fact is mentioned.

## Do not search for

Do not generate queries for:
- The user's own name
- Unchanged facts
- Facts introduced only by the assistant
- Facts the assistant recalled from memory without new user confirmation
- Temporary conversational details that are not durable
- Questions that do not establish a durable user fact
- Purely informational questions where the user does not reveal anything
  durable about themselves

## Important retrieval principle

Favor RECALL over precision.

It is acceptable for a query to retrieve a few related memories that later
turn out not to require modification.

It is NOT acceptable to miss an existing memory that the user's new
information may revise.

Generate multiple queries when one user statement could affect multiple
independent existing memories.

Only produce queries when there is potentially memory-worthy NEW or CHANGED
information.

Return an empty list when there is nothing durable that could affect existing
memories.

Reference time:
{reference_utc}

Conversation:
{context}
""".strip()


def memory_trustcall_prompt(
    context: str,
    *,
    existing: list[Memory],
    document_id: str | None = None,
    now: datetime | None = None,
) -> str:
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    reference_utc = reference.astimezone(timezone.utc).isoformat()

    existing_block = "\n".join(
        f"- id={memory.id}: {memory.content} "
        f"(category={memory.category}, "
        f"document_id={memory.document_id or 'null'}, "
        f"expires_at={memory.expires_at.isoformat() if memory.expires_at else 'null'})"
        for memory in existing
    ) or "- (none)"
    active_document = document_id or "null"

    return f"""Maintain the user's durable memories using ONLY new information
explicitly provided by the user in this conversation.

The existing memories below were retrieved because they may be related to the
conversation. Decide whether each relevant memory should be PATCHED, REMOVED,
or left unchanged, and whether any genuinely new memory should be INSERTED.

## Existing memories

{existing_block}

## Active document

Active document_id: {active_document}

## Core principle

Compare facts by MEANING, not wording.

A new statement should PATCH an existing memory when it updates, progresses,
contradicts, replaces, or otherwise changes the same underlying fact.

Do not create a new memory merely because the user expressed the same fact
using different words.

Examples:

Existing:
"The user is learning binary trees."

New:
"I finished studying binary trees."

→ PATCH the existing memory:
"The user has finished studying binary trees."

Existing:
"The user struggles with recursion."

New:
"I finally understand recursion."

→ PATCH the existing memory:
"The user understands recursion after previously struggling with it."

Existing:
"The user is preparing for the IELTS exam."

New:
"I took the IELTS yesterday."

→ PATCH the existing IELTS memory because the user's status changed.

Existing:
"The user prefers Python."

New:
"I prefer Go now instead of Python."

→ REMOVE the Python preference and INSERT:
"The user prefers Go."

Existing:
"The user is interested in fintech."

New:
"I also want to work in developer tooling."

→ INSERT a new memory if the two interests can coexist.

Do NOT treat merely mentioning a topic as a change to an existing memory.

## What may be stored

Only store NEW or CHANGED durable information explicitly stated by the user.

Do NOT store:

- The user's own name.
- Information stated only by the assistant.
- Information retrieved from memory and merely repeated by the assistant.
- Unchanged information.
- Temporary conversational details with no lasting usefulness.
- Guesses, assumptions, or conclusions not established by the user.
- A user's question as a fact unless the question itself clearly establishes
  a durable preference, goal, difficulty, or other memory-worthy fact.

## Actions

For each memory-worthy fact, choose one of:

### PATCH

Patch an existing memory when it represents the same underlying fact and the
user has provided newer or changed information.

Preserve useful historical context when appropriate.

For example:

Old:
"The user struggles with recursion."

New:
"I finally understand recursion."

Better result:
"The user understands recursion after previously struggling with it."

Do not erase useful progress history merely because the current state changed.

### INSERT

Insert a new memory when the fact is genuinely distinct and can coexist with
existing memories.

Do not insert near-duplicates.

### REMOVE

Remove an existing memory when:

- The user clearly abandons or negates the fact and no replacement belongs
  on that same memory.
- The memory has expired.
- The user explicitly replaces the old preference with a new preference.

Do not remove a memory merely because the user mentioned a different option.

### NO ACTION

Do nothing when the information is unchanged, temporary, ambiguous, or not
durable.

When uncertain, prefer NO ACTION over guessing.

## Preferences

When the user explicitly changes a preference:

"I prefer Y now instead of X."

Remove the old X preference and insert the Y preference.

When the user merely says they are considering, trying, or interested in Y,
do not assume that their previous X preference has been replaced.

## Progress

Progress should normally PATCH an existing memory about the same topic.

Examples:

"The user is learning databases."
+
"I finished the database course."

→ PATCH the existing progress memory.

"The user is studying binary trees."
+
"I've started graphs now."

→ Patch the binary-tree memory only if the new statement clearly establishes
completion or a changed status. Otherwise, insert a separate graph-progress
memory.

Do not merge unrelated academic topics into one memory.

## Atomicity

Each memory must represent ONE durable atomic fact.

Do not combine unrelated facts into a single memory.

For example, do not create:
"The user prefers Go, studies for two hours daily, and wants to work in fintech."

Instead create separate memories when each fact is independently durable.

## Memory content format

Every memory must be a complete sentence beginning with "The user" or
"The user's".

Good:
- "The user prefers step-by-step explanations."
- "The user is currently studying binary trees."
- "The user is preparing for the IELTS exam."

Bad:
- "Prefers step-by-step explanations."
- "Learning binary trees."
- "IELTS tomorrow."

Never store:
"The user's name is Peter."

The user's own name is already stored on their profile.

## Categories

Pick exactly ONE category for every INSERTED or PATCHED memory.

{taxonomy_description()}

Use these boundaries:

- learning_preferences:
  How the user prefers to learn or study.

- academic_struggles:
  Academic topics or skills the user finds difficult, confusing, or needs
  extra help with.

- academic_progress:
  Topics, courses, skills, units, or milestones the user has started,
  completed, mastered, or is currently working on.

- tests_exams:
  Specific tests or exams, including preparation, status, scores, deadlines,
  goals, and exam-related concerns.

- user_personality:
  Durable information about the user outside pure academics, including
  interests, motivation, work/life context, hobbies, constraints, family,
  and relevant information about other people.

Choose the category based on the PRIMARY meaning of the memory.

Examples:

"The user struggles with recursion."
→ academic_struggles

"The user understands recursion now."
→ academic_progress

"The user prefers recursion to be explained visually."
→ learning_preferences

"The user is preparing for the IELTS exam."
→ tests_exams

"The user is interested in fintech."
→ user_personality

Do not create multiple copies of the same fact just because it could relate to
more than one category.

## document_id

document_id may ONLY be set for:

- learning_preferences
- academic_progress
- tests_exams

If the fact specifically concerns the active document, set document_id to the
active document_id.

Otherwise set document_id to null.

For:
- user_personality
- academic_struggles

document_id MUST be null.

## expires_at

Set expires_at ONLY when the user provides a clear time bound.

Otherwise set it to null.

Always convert time expressions into an absolute UTC datetime using the
reference time below.

Resolve expressions such as:
- "tomorrow"
- "next week"
- "in 3 days"
- "next month"
- "July 14"
- "14th of July"
- "on Friday"

When a year is omitted, use the next occurrence on or after the reference
date.

When a named day has no explicit time, use 23:59:59 UTC on that day.

Never store relative expressions such as "tomorrow" in expires_at.

Never invent an expiration date.

Any loaded memory whose expires_at is before the reference time MUST be
removed.

## Final rules

1. Use only information explicitly provided by the user.
2. Compare memories by semantic meaning, not wording.
3. Patch before inserting when the same underlying fact already exists.
4. Never create near-duplicate memories.
5. Preserve useful progress history when patching.
6. Explicitly replaced preferences should remove the old preference and insert
   the new one.
7. Do not infer that a preference changed merely because another option was
   mentioned.
8. Keep memories atomic.
9. Remove expired loaded memories.
10. When uncertain, do nothing rather than guess.
11. Use parallel operations for independent patches, inserts, and removals.

Reference time:
{reference_utc}

Conversation:
{context}
""".strip()
