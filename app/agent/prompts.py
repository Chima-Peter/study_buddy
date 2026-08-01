"""Centralized prompts for the study buddy agent."""

from app.memory.schema import taxonomy_description


def retrieval_decider_prompt(query: str) -> str:
    return (
        "Decide what context is needed to answer the user.\n\n"
        "Choose exactly one document/history decision:\n"
        '- "rag": the question is about uploaded study documents\n'
        '- "history": the question refers to prior chat turns only\n'
        '- "both": the question needs both documents and prior chat turns\n'
        '- "none": no document or chat-history retrieval needed\n\n'
        "Separately set retrieve_memory:\n"
        "- true when the answer depends on durable facts about this student "
        "(preferences, goals, subjects, strengths/weaknesses, "
        "progress, resources, habits, achievements)\n"
        "- false when the question is only about uploaded documents, "
        "general knowledge, or this chat without needing stored student facts\n"
        "- name and gender are always loaded when missing; do not set "
        "retrieve_memory=true only for those\n\n"
        "Memory taxonomy (category: types):\n"
        f"{taxonomy_description()}\n\n"
        'Choose "none" for document/history when general knowledge is enough.\n'
        'Choose "rag" only when the question is clearly about study materials.\n'
        "Memory retrieval can be true even when decision is \"none\" "
        "(e.g. personalization-only questions).\n\n"
        f"Question: {query}\n"
    )


def rewrite_query_prompt(
    query: str,
    conversation_summary: str | None,
    recent_history: list,
    *,
    retrieve_rag: bool,
    retrieve_memory: bool,
) -> str:
    parts = [
        "Rewrite the user's question for retrieval. "
        "Resolve references using the conversation context, preserve the "
        "original meaning and important terms, and do not answer the question.\n",
    ]
    if retrieve_rag:
        parts.append(
            "Set rag_query to a rewritten hybrid document-search query.\n"
        )
    else:
        parts.append("Set rag_query to null (document retrieval is disabled).\n")

    if retrieve_memory:
        parts.append(
            "Set memory_queries to one or more memory-index searches. "
            "Each entry needs content, category, and type from the taxonomy. "
            "Use multiple entries when the question needs distinct memory "
            "slices (e.g. learning weaknesses and study habits). "
            "Each content value should be a concise fact-seeking query "
            "scoped to that slice. "
            "Do not include name or gender lookups; those are fetched "
            "automatically.\n"
            f"Memory taxonomy (category: types):\n{taxonomy_description()}\n"
        )
    else:
        parts.append(
            "Set memory_queries to an empty list "
            "(memory retrieval is disabled).\n"
        )

    parts.append(
        f"\nConversation summary: {conversation_summary or ''}\n"
        f"Recent conversation: {recent_history}\n"
        f"Question: {query}\n"
    )
    return "".join(parts)


def title_prompt(query: str, response: str) -> str:
    return (
        "Generate a short title for this study conversation.\n\n"
        "Rules:\n"
        "1. Return only the title text\n"
        "2. Keep it under 80 characters\n"
        "3. Include specific details: document name, chapter, topic, or key concept\n"
        "4. Do not wrap in quotes or end with punctuation\n"
        "5. Avoid generic titles like 'Questions About...' or 'Help With...'\n\n"
        'Good: "Photosynthesis Ch3: Light Reactions & Calvin Cycle"\n'
        'Bad: "Questions About Biology Textbook"\n\n'
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
        f"Current summary: {current_summary or '(none)'}\n\n"
        f"Recent exchanges:\n{chr(10).join(recent_exchanges)}\n\n"
        "Rules:\n"
        "1. Return only the summary text\n"
        "2. Keep it under 255 characters\n"
        "3. Include specific details: document names, chapter numbers, key terms, concepts covered\n"
        "4. Focus on WHAT was learned/discussed, not meta-descriptions like 'user asked about...'\n"
        "5. Do not wrap in quotes or end with punctuation\n\n"
        'Good: "Photosynthesis in Ch3 of Biology 101: light reactions, Calvin cycle, chloroplast structure"\n'
        'Bad: "The user asked questions about photosynthesis from their biology textbook"'
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
    return (
        "You are a helpful study assistant.\n\n"
        "Use the provided context as the primary source of truth when "
        "answering questions about the user's documents or study materials.\n"
        "Use student memories to personalize tutoring when relevant "
        "(preferences, goals, strengths, schedule, etc.).\n"
        "Address the student by name when known.\n\n"
        "Rules:\n"
        "1. If the answer can be found in the provided context, answer using "
        "only that context.\n"
        "2. If the question is about the uploaded documents but the context "
        "does not contain enough information, ask the user "
        "to upload the relevant document(s) or provide additional context. Do "
        "not guess or fabricate information.\n"
        "3. If the question is a general knowledge question that is unrelated "
        'to the uploaded documents (e.g., "What is the capital of France?"), '
        "answer normally using your general knowledge.\n"
        "4. If it is unclear whether the question refers to the uploaded "
        "documents or general knowledge, answer from your general knowledge.\n"
        "5. When answering from the provided context, cite or reference the "
        "relevant sections if they are available.\n"
        "6. Treat student memories as known facts about this learner; do not "
        "invent memories that are not listed.\n\n"
        f"Student name: {student_name or '(unknown)'}\n"
        f"Student gender: {student_gender or '(unknown)'}\n\n"
        f"External Context:\n{context}\n\n"
        f"Student Memories:\n{memories or '(none)'}\n\n"
        f"Conversation Last 5 Messages:\n{conversation_history_prompt}\n\n"
        f"Conversation Summary:\n{conversation_summary}\n\n"
        f"Question: {query}\n"
        "Answer:"
    )
