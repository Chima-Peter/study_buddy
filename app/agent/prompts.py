"""Centralized prompts for the study buddy agent."""


def retrieval_decider_prompt(query: str) -> str:
    return (
        "Decide what context is needed to answer the user.\n\n"
        "Choose exactly one:\n"
        '- "rag": the question is about uploaded study documents\n'
        '- "history": the question refers to prior chat turns only\n'
        '- "both": the question needs both documents and prior chat turns\n'
        '- "none": general knowledge question (e.g. capitals, math, definitions)\n\n'
        'Choose "none" for questions you can answer from general knowledge.\n'
        'Choose "rag" only when the question is clearly about study materials.\n\n'
        f"Question: {query}\n"
    )


def rewrite_query_prompt(
    query: str,
    conversation_summary: str | None,
    recent_history: list,
) -> str:
    return (
        "Rewrite the user's question for hybrid document search.\n"
        "Resolve references using the conversation context, preserve the "
        "original meaning and important terms, and do not answer the question.\n"
        "Return only the rewritten search query.\n\n"
        f"Conversation summary: {conversation_summary or ''}\n"
        f"Recent conversation: {recent_history}\n"
        f"Question: {query}\n"
    )


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
) -> str:
    return (
        "You are a helpful study assistant.\n\n"
        "Use the provided context as the primary source of truth when "
        "answering questions about the user's documents or study materials.\n\n"
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
        "relevant sections if they are available.\n\n"
        f"External Context:\n{context}\n\n"
        f"Conversation Last 5 Messages:\n{conversation_history_prompt}\n\n"
        f"Conversation Summary:\n{conversation_summary}\n\n"
        f"Question: {query}\n"
        "Answer:"
    )
