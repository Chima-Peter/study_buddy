"""Centralized prompts for the study buddy agent."""


def retrieval_decider_prompt(query: str, context: str) -> str:
    return (
        "Decide what context is needed to answer the user's question.\n\n"
        "Choose exactly one for decision:\n"
        '- "rag": question requires retrieval from uploaded study documents to generate a very detailed answer\n'
        '- "history": question refers to prior chat turns only\n'
        '- "both": question requires retrieval from both documents and prior chat\n'
        '- "none": general knowledge question, no retrieval needed\n\n'
        "Set retrieve_memory:\n"
        "- true: answer needs stored student facts (topics, preferences, style, schedule)\n"
        "- false: greetings/small talk (hi, hello, thanks), document-only lookup, "
        "general knowledge, or chat that does not need stored student facts\n"
        "Note: Name and gender come from user profile automatically, not from memory.\n\n"
        "Set is_academic_discussion:\n"
        "- true: study/academic content (concepts, homework, exams, documents, "
        "courses, study plans) OR brief allowed interaction "
        "(greetings, thanks, short clarifying replies, light small talk that "
        "keeps a study session going)\n"
        "- false: clearly off-topic or non-academic requests with no study "
        "purpose (unrelated entertainment, general life advice, tasks outside "
        "learning). Prefer true when unsure if the query could support studying\n\n"
        f"Question: {query}\n"
        f"Context: {context}\n"
    )


def rewrite_query_prompt(
    query: str,
    conversation_summary: str | None,
    recent_history: list,
    *,
    retrieve_rag: bool,
    retrieve_memory: bool,
    section_keys: list[str] | None = None,
) -> str:
    if retrieve_rag and retrieve_memory:
        retrieval_type = "both"
    elif retrieve_rag:
        retrieval_type = "rag"
    elif retrieve_memory:
        retrieval_type = "memory"
    else:
        retrieval_type = "none"

    parts = [
        "Rewrite the user's question for retrieval.\n"
        "Resolve pronouns and references using conversation context. "
        "Preserve original meaning and key terms. Do not answer the question.\n\n"
        f"Retrieval type: {retrieval_type}\n\n"
    ]

    if retrieve_rag:
        parts.append(
            "Set rag_query to a rewritten search query for documents.\n"
        )
        if section_keys:
            keys_list = ", ".join(section_keys)
            parts.append(
                "Available section keys (from document chapter split):\n"
                f"{keys_list}\n"
                "If the user scopes the question to specific chapters/parts/"
                "units (e.g. 'from chapter 1', 'chapter 2 and 3'), set "
                "chapters to the matching keys from that list only. "
                "Copy keys exactly. "
                "Map mentions like 'chapter 1' / 'Ch. 1' -> chapter_1 when "
                "that key exists.\n"
                "Examples: 'from chapter 1 and chapter 2' with keys "
                "chapter_1,chapter_2 -> [\"chapter_1\", \"chapter_2\"]; "
                "'explain photosynthesis' (no chapter) -> [] or null.\n"
                "Do not invent keys that are not in the available list.\n"
            )
        else:
            parts.append(
                "No section keys are available for these documents. "
                "Set chapters to null.\n"
            )
    else:
        parts.append(
            "Set rag_query to null and chapters to null "
            "(document retrieval disabled).\n"
        )

    if retrieve_memory:
        parts.append(
            "Set memory_query to ONE partial statement for the memory store.\n"
            "Phrase like stored memories - start with 'The user'.\n"
            "Combine needed aspects into a single phrase.\n"
            "Good: 'The user is interested in and prefers'\n"
            "Bad: 'What does the user like?' (question format won't match)\n"
            "Do NOT include name/gender lookups - those come from profile.\n"
        )
    else:
        parts.append("Set memory_query to null (memory retrieval disabled).\n")

    parts.append(
        f"\nConversation summary: {conversation_summary or '(none)'}\n"
        f"Recent history: {recent_history}\n"
        f"Question: {query}\n"
    )
    return "".join(parts)


def title_prompt(query: str, response: str) -> str:
    return (
        "Generate a short title for this study conversation.\n\n"
        "Rules:\n"
        "- Under 80 characters\n"
        "- Include specific topic, chapter, or concept\n"
        "- No quotes or trailing punctuation\n"
        "- Avoid generic phrases like 'Questions About' or 'Help With'\n\n"
        'Good: "Photosynthesis Ch3 Light Reactions"\n'
        'Bad: "Biology Questions"\n\n'
        f"Question: {query}\n"
        f"Answer: {response[:300]}\n"
        "Title:"
    )


def summary_prompt(
    current_summary: str | None,
    recent_exchanges: list[str],
) -> str:
    return (
        "Update the running summary of this study conversation.\n\n"
        "Write topics covered as facts, not narration.\n"
        "Good: 'Covered photosynthesis Ch3: light reactions, Calvin cycle'\n"
        "Bad: 'The user asked about photosynthesis'\n\n"
        "Keep: subjects, chapters, concepts, problems solved.\n"
        "Skip: chit-chat, greetings, vague phrases.\n\n"
        "Rules:\n"
        "- Max 1500 characters\n"
        "- Merge with current summary; don't drop still-relevant facts\n"
        "- Be specific with topic names\n\n"
        f"Current summary: {current_summary or '(none)'}\n\n"
        f"Recent exchanges:\n{chr(10).join(recent_exchanges)}\n"
    )


def chat_response_prompt(
    context: str,
    conversation_history_prompt: str,
    conversation_summary: str,
    query: str,
    memories: str = "",
    student_name: str | None = None,
    student_gender: str | None = None,
) -> str:
    has_history = bool(conversation_history_prompt or conversation_summary)

    greeting_rule = (
        "8. Do NOT repeat introductory greetings (e.g., 'Hello [name], nice to meet you') "
        "if conversation history exists - the student already knows you\n"
        if has_history
        else ""
    )

    return (
        "You are a helpful study assistant.\n\n"
        "Rules:\n"
        "1. If the answer is in the provided context, answer using that context\n"
        "2. If the question is about documents but context is insufficient, "
        "ask the user to upload relevant documents - do not fabricate\n"
        "3. For general knowledge unrelated to documents, answer normally\n"
        "4. Cite relevant sections when answering from context\n"
        "5. Use student memories to personalize (preferences, goals, strengths)\n"
        "6. Address the student by name when known\n"
        "7. Always format the answer in Markdown: use headings (## / ###), "
        "bullet/numbered lists, bold/italic emphasis, fenced code blocks when "
        "useful, tables for comparisons or structured facts, and images via "
        "![alt text](url) when a diagram, figure, or illustration aids "
        "understanding. Prefer clear, scannable study notes over plain-text walls\n"
        f"{greeting_rule}\n"
        f"Student name: {student_name or '(unknown)'}\n"
        f"Student gender: {student_gender or '(unknown)'}\n\n"
        f"Document Context:\n{context or '(none)'}\n\n"
        f"Student Memories:\n{memories or '(none)'}\n\n"
        f"Recent History:\n{conversation_history_prompt or '(none)'}\n\n"
        f"Conversation Summary:\n{conversation_summary or '(none)'}\n\n"
        f"Question: {query}\n"
    )
