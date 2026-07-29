from logging import Logger

from langchain_google_genai import ChatGoogleGenerativeAI
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
        if state["conversation_id"] is not None:
            self.logger.info(
                "Create conversation node skipped id=%s user_id=%s",
                state["conversation_id"],
                state["user_id"],
            )
            return {}

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


class RetrieveDocumentsNode():
    def __init__(self, retriever: RAGRetriever, logger: Logger):
        self.retriever = retriever
        self.logger = logger

    async def __call__(self, state: AgentState) -> AgentState:
        self.logger.info(
            "Retrieve documents node started user_id=%s",
            state["user_id"],
        )
        results = await self.retriever.retrieve(
            user_id=state["user_id"],
            query=state["query"],
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
            writer(chunk)
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
        if not state["first_message"]:
            self.logger.info(
                "Update title node skipped id=%s user_id=%s",
                state["conversation_id"],
                state["user_id"],
            )
            return {}

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
        history_count = len(conversation_history)
        if history_count == 0 or history_count % 5 != 0:
            self.logger.info(
                "Update summary node skipped id=%s user_id=%s in count=%s",
                state["conversation_id"],
                state["user_id"],
                history_count % 5,
            )
            return {}

        self.logger.info(
            "Update summary node started id=%s user_id=%s",
            state["conversation_id"],
            state["user_id"],
        )
        summary_prompt = f"""
            Generate a summary for this study conversation.\n\n
            Rules:
            1. Return only the summary text.
            2. Keep it under 255 characters.
            3. Capture the main topic of the user's question.
            4. Do not wrap the summary in quotes.
            5. Do not end with punctuation.
            This is the current summary of the conversation: {state["conversation_summary"]}
            This are the last 5 chats in the conversation: {conversation_history[-5:]}
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
