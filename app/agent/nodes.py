from logging import Logger

from langchain_google_genai import ChatGoogleGenerativeAI
from app.agent.schema import SUMMARY_EVERY, DeciderResponse
from app.agent.state import AgentState
from app.rag.retriever import RAGRetriever
from app.system.schemas.conversation import CreateConversationRequest, UpdateConversationTitleRequest
from app.system.service.chat import ChatService
from app.system.service.conversation import ConversationService
from langgraph.config import get_stream_writer

class CreateConversationNode():
    def __init__(
        self,
        conversation_service: ConversationService,
        logger: Logger,
    ):
        self.conversation_service = conversation_service
        self.logger = logger

    async def __call__(self, state: AgentState) -> AgentState:
        self.logger.info(
            "Create conversation node started user_id=%s",
            state["user_id"],
        )
        conversation = await self.conversation_service.create(
            CreateConversationRequest(title="New Conversation"),
            user_id=state["user_id"],
        )
        self.logger.info(
            "Create conversation node completed id=%s user_id=%s",
            conversation.id,
            state["user_id"],
        )
        return {"conversation_id": conversation.id}


class RetrievalDeciderNode():
    def __init__(self, logger: Logger, model: ChatGoogleGenerativeAI):
        self.logger = logger
        self.model = model.with_structured_output(DeciderResponse)

    async def __call__(self, state: AgentState) -> AgentState:
        # First turn has no history worth loading.
        if state["first_message"]:
            self.logger.info(
                "Retrieval decider skipped for first message user_id=%s",
                state["user_id"],
            )
            return {
                "retrieve_rag": True,
                "retrieve_conversation_history": False,
            }

        self.logger.info(
            "Retrieval decider started id=%s user_id=%s",
            state["conversation_id"],
            state["user_id"],
        )
        prompt = (
            "Decide what context is needed to answer the user.\n\n"
            "Choose exactly one:\n"
            '- "rag": the question is about uploaded study documents\n'
            '- "history": the question refers to prior chat turns only\n'
            '- "both": the question needs both documents and prior chat turns\n'
            '- "none": general knowledge question (e.g. capitals, math, definitions)\n\n'
            'Choose "none" for questions you can answer from general knowledge.\n'
            'Choose "rag" only when the question is clearly about study materials.\n\n'
            f"Question: {state['query']}\n"
        )
        try:
            decision = await self.model.ainvoke(prompt)
            result = decision.decision
        except Exception:
            self.logger.exception(
                "Retrieval decider failed id=%s user_id=%s",
                state["conversation_id"],
                state["user_id"],
            )
            result = "both"

        mapping = {
            "rag": (True, False),
            "history": (False, True),
            "both": (True, True),
            "none": (False, False),
        }
        retrieve_rag, retrieve_history = mapping.get(result, (False, False))
        self.logger.info(
            "Retrieval decider completed id=%s user_id=%s decision=%s",
            state["conversation_id"],
            state["user_id"],
            result,
        )
        return {
            "retrieve_rag": retrieve_rag,
            "retrieve_conversation_history": retrieve_history,
        }


class RewriteQueryNode():
    def __init__(self, logger: Logger, model: ChatGoogleGenerativeAI):
        self.logger = logger
        self.model = model

    async def __call__(self, state: AgentState) -> AgentState:
        if not state["retrieve_rag"]:
            self.logger.info(
                "Rewrite query node skipped id=%s user_id=%s",
                state["conversation_id"],
                state["user_id"],
            )
            return {"rewritten_query": state["query"]}

        self.logger.info(
            "Rewrite query node started id=%s user_id=%s",
            state["conversation_id"],
            state["user_id"],
        )
        recent_history = state["conversation_history"][-3:]
        prompt = (
            "Rewrite the user's question for hybrid document search.\n"
            "Resolve references using the conversation context, preserve the "
            "original meaning and important terms, and do not answer the question.\n"
            "Return only the rewritten search query.\n\n"
            f"Conversation summary: {state['conversation_summary'] or ''}\n"
            f"Recent conversation: {recent_history}\n"
            f"Question: {state['query']}\n"
        )
        response = await self.model.ainvoke(prompt)
        result = (response.text or "").strip() or state["query"]
        self.logger.info(
            "Rewrite query node completed id=%s user_id=%s",
            state["conversation_id"],
            state["user_id"],
        )
        return {"rewritten_query": result}

class RetrieveDocumentsNode():
    def __init__(self, retriever: RAGRetriever, logger: Logger):
        self.retriever = retriever
        self.logger = logger

    async def __call__(self, state: AgentState) -> AgentState:
        if not state["retrieve_rag"]:
            self.logger.info(
                "Retrieve documents node skipped user_id=%s",
                state["user_id"],
            )
            return {"rag_documents": []}

        self.logger.info(
            "Retrieve documents node started user_id=%s",
            state["user_id"],
        )
        results = await self.retriever.retrieve(
            user_id=state["user_id"],
            query=state["rewritten_query"],
            mode="hybrid",
        )

        self.logger.info(
            "Retrieve documents node completed user_id=%s count=%s",
            state["user_id"],
            len(results),
        )
        return {"rag_documents": results}


class RetrieveConversationHistoryNode():
    def __init__(
        self,
        conversation_service: ConversationService,
        logger: Logger,
    ):
        self.conversation_service = conversation_service
        self.logger = logger

    async def __call__(self, state: AgentState) -> AgentState:
        if not state["retrieve_conversation_history"]:
            self.logger.info(
                "Retrieve history node skipped id=%s user_id=%s",
                state["conversation_id"],
                state["user_id"],
            )
            return {
                "conversation_history": [],
                "conversation_summary": None,
            }

        self.logger.info(
            "Retrieve history node started id=%s user_id=%s",
            state["conversation_id"],
            state["user_id"],
        )
        results = await self.conversation_service.get(
            user_id=state["user_id"],
            conversation_id=state["conversation_id"],
        )
        if results is None:
            raise ValueError("Conversation not found")

        self.logger.info(
            "Retrieve history node completed id=%s user_id=%s count=%s",
            state["conversation_id"],
            state["user_id"],
            len(results.chats),
        )
        return {
            "conversation_history": results.chats,
            "conversation_summary": results.summary or "",
        }


class GenerateResponseNode():
    def __init__(self, retriever: RAGRetriever, logger: Logger):
        self.retriever = retriever
        self.logger = logger

    async def __call__(self, state: AgentState) -> AgentState:
        self.logger.info(
            "Generate response node started id=%s user_id=%s documents=%s history=%s",
            state["conversation_id"],
            state["user_id"],
            len(state["rag_documents"]),
            len(state["conversation_history"]),
        )
        writer = get_stream_writer()
        answer = ""
        async for chunk in self.retriever.generate_chat_response(
            user_id=state["user_id"],
            query=state["query"],
            rag_documents=state["rag_documents"],
            conversation_summary=state["conversation_summary"],
            conversation_history=state["conversation_history"],
        ):
            writer({
                "chunk": chunk,
                "conversation_id": state["conversation_id"],
            })
            answer += chunk

        self.logger.info(
            "Generate response node completed id=%s user_id=%s response_chars=%s",
            state["conversation_id"],
            state["user_id"],
            len(answer),
        )
        return {"response": answer}


class SaveChatNode():
    def __init__(self, chat_service: ChatService, logger: Logger):
        self.chat_service = chat_service
        self.logger = logger

    async def __call__(self, state: AgentState) -> AgentState:
        sources = [
            {
                "content": r.document.content,
                "metadata": r.document.metadata,
                "embedding": r.document.embedding,
                "rrf_score": r.score,
            }
            for r in state["rag_documents"]
        ]
        self.logger.info(
            "Save chat node started id=%s user_id=%s sources=%s",
            state["conversation_id"],
            state["user_id"],
            len(sources),
        )
        chat = await self.chat_service.save(
            user_id=state["user_id"],
            conversation_id=state["conversation_id"],
            query=state["query"],
            response=state["response"],
            source=sources,
        )
        if chat is None:
            self.logger.warning(
                "Save chat node failed id=%s user_id=%s",
                state["conversation_id"],
                state["user_id"],
            )
            return {}

        self.logger.info(
            "Save chat node completed id=%s user_id=%s",
            state["conversation_id"],
            state["user_id"],
        )

        return {"conversation_history": [chat]}


class UpdateConversationTitleNode():
    def __init__(
        self,
        conversation_service: ConversationService,
        model: ChatGoogleGenerativeAI,
        logger: Logger,
    ):
        self.conversation_service = conversation_service
        self.model = model
        self.logger = logger

    async def __call__(self, state: AgentState) -> AgentState:
        self.logger.info(
            "Update title node started id=%s user_id=%s",
            state["conversation_id"],
            state["user_id"],
        )
        title_prompt = (
                "Generate a short title for this study conversation.\n\n"
                "Rules:\n"
                "1. Return only the title text.\n"
                "2. Keep it under 80 characters.\n"
                "3. Capture the main topic of the user's question.\n"
                "4. Do not wrap the title in quotes.\n"
                "5. Do not end with punctuation.\n\n"
                f"Question: {state["query"]}\n"
                f"Answer: {state["response"]}\n"
                "Title:"
            )
        title_response = await self.model.ainvoke(title_prompt)
        title = (title_response.text or "").strip().strip("\"'")[:255] or None
        if title is None:
            self.logger.warning(
                "Update title node produced empty title id=%s user_id=%s",
                state["conversation_id"],
                state["user_id"],
            )
            return {"title": None}

        await self.conversation_service.update_title(
            conversation_id=state["conversation_id"],
            user_id=state["user_id"],
            request=UpdateConversationTitleRequest(
                title=title,
            ),
        )

        self.logger.info(
            "Update title node completed id=%s user_id=%s",
            state["conversation_id"],
            state["user_id"],
        )
        return {"title": title}


class UpdateConversationSummaryNode():
    def __init__(
        self,
        conversation_service: ConversationService,
        model: ChatGoogleGenerativeAI,
        logger: Logger,
    ):
        self.conversation_service = conversation_service
        self.model = model
        self.logger = logger

    async def __call__(self, state: AgentState) -> AgentState:
        conversation_history = state["conversation_history"]
        user_messages = [chat.query for chat in conversation_history]

        self.logger.info(
            "Update summary node started id=%s user_id=%s",
            state["conversation_id"],
            state["user_id"],
        )

        summary_prompt = f"""
            Generate a summary for this conversation.

            Current summary: {state["conversation_summary"]}
            Last {SUMMARY_EVERY} user messages: {user_messages[-SUMMARY_EVERY:]}

            Rules:
            1. Return only the summary text
            2. Keep it under 255 characters
            3. Capture the main topic of the user's question
            4. Do not wrap the summary in quotes
            5. Do not end with punctuation
        """

        summary_response = await self.model.ainvoke(summary_prompt)
        summary = (
            (summary_response.text or "").strip().strip("\"'")[:255]
            or state["conversation_summary"]
        )

        await self.conversation_service.update_summary(
            conversation_id=state["conversation_id"],
            user_id=state["user_id"],
            summary=summary,
        )
        self.logger.info(
            "Update summary node completed id=%s user_id=%s summary_chars=%s",
            state["conversation_id"],
            state["user_id"],
            len(summary),
        )
        return {"conversation_summary": summary}
