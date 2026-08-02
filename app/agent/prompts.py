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
        "(personal, academic, or learning memories)\n"
        "- false when the question is only about uploaded documents, "
        "general knowledge, or this chat without needing stored student facts\n"
        "- name and gender are always loaded when missing; do not set "
        "retrieve_memory=true only for those\n\n"
        "Memory categories:\n"
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
            "Set memory_queries to one or more simple questions for the "
            "memory store. Each entry needs:\n"
            "- content: a short plain question, like "
            "'What is the user\\'s name?', "
            "'Which university does the user attend?', "
            "'What subjects does the user take?', "
            "'What are the user\\'s weak topics?'\n"
            "- category: exactly one of personal, academic, learning\n"
            "Pick category using these conditions:\n"
            "- personal: identity, schedule, life goals, constraints\n"
            "- academic: university, subjects, exams, resources\n"
            "- learning: strengths, weaknesses, style, pace, mastery\n"
            "Use multiple entries when distinct categories are needed. "
            "Do not include name or gender lookups; those are fetched "
            "automatically.\n"
            f"Categories:\n{taxonomy_description()}\n"
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
        "Write one complete, self-contained summary.\n"
        "State what was covered as facts, not as a narration of the chat.\n"
        "Include the user's name when it is known.\n\n"
        "Good:\n"
        "- Peter covered photosynthesis in Biology 101 Ch3: light reactions, "
        "Calvin cycle, chloroplast structure\n"
        "- Peter worked through CSC linked-list insertion and deletion examples\n\n"
        "Bad:\n"
        "- The user asked questions about photosynthesis\n"
        "- Helped with some CSC topics\n"
        "- Discussed the chapter\n\n"
        "Keep: document/chapter names, subjects, key terms, concepts solved, "
        "specific problems worked on.\n"
        "Skip: chit-chat, greetings, meta lines like 'user asked about...', "
        "vague phrases with no topic detail.\n\n"
        "Rules:\n"
        "1. Return only the summary text\n"
        "2. Keep it under 1500 characters\n"
        "3. Merge with the current summary; do not drop still-relevant facts\n"
        "4. Be exact and concrete; prefer nouns and topic names over verbs about asking\n"
        "5. Do not wrap in quotes or end with punctuation\n\n"
        f"Current summary: {current_summary or '(none)'}\n\n"
        f"Recent exchanges:\n\n{'\n'.join(recent_exchanges)}\n"
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
