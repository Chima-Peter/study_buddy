import asyncio
from logging import Logger

from langchain_google_genai import ChatGoogleGenerativeAI
from app.agent.prompts import (
    chat_response_prompt,
    retrieval_decider_prompt,
    rewrite_query_prompt,
    summary_prompt,
    title_prompt,
)
from app.agent.schema import (
    SUMMARY_EVERY,
    SUMMARY_MAX_CHARS,
    DeciderResponse,
    RewriteQueryResponse,
)
from app.agent.state import AgentState
from app.authentication.repository.user_repository import UserRepository
from app.memory.schema import Memory, MemoryRetrievalQuery
from app.memory.service import MemoryService
from app.rag.rag_retriever import RAGRetriever
from app.system.schemas.conversation import UpdateConversationTitleRequest
from app.system.service.chat import ChatService
from app.system.service.conversation import ConversationService
from langgraph.config import get_stream_writer


class RetrievalDeciderNode():
    def __init__(self, logger: Logger, model: ChatGoogleGenerativeAI):
        self.logger = logger
        self.model = model.with_structured_output(DeciderResponse)

    async def __call__(self, state: AgentState) -> AgentState:
        self.logger.info(
            "Retrieval decider started id=%s user_id=%s first_message=%s",
            state["conversation_id"],
            state["user_id"],
            state["first_message"],
        )
        prompt = retrieval_decider_prompt(state["query"])
        try:
            decision = await self.model.ainvoke(prompt)
            result = decision.decision
            retrieve_memory = decision.retrieve_memory
        except Exception:
            self.logger.exception(
                "Retrieval decider failed id=%s user_id=%s",
                state["conversation_id"],
                state["user_id"],
            )
            result = "both" if not state["first_message"] else "rag"
            retrieve_memory = False

        mapping = {
            "rag": (True, False),
            "history": (False, True),
            "both": (True, True),
            "none": (False, False),
        }
        retrieve_rag, retrieve_history = mapping.get(result, (False, False))
        # First turn has no history worth loading.
        if state["first_message"]:
            retrieve_history = False

        self.logger.info(
            "Retrieval decider completed id=%s user_id=%s decision=%s "
            "retrieve_rag=%s retrieve_history=%s retrieve_memory=%s",
            state["conversation_id"],
            state["user_id"],
            result,
            retrieve_rag,
            retrieve_history,
            retrieve_memory,
        )
        return {
            "retrieve_rag": retrieve_rag,
            "retrieve_conversation_history": retrieve_history,
            "retrieve_memory": retrieve_memory,
        }


class RewriteQueryNode():
    def __init__(self, logger: Logger, model: ChatGoogleGenerativeAI):
        self.logger = logger
        self.model = model

    async def __call__(self, state: AgentState) -> AgentState:
        retrieve_rag = state["retrieve_rag"]
        retrieve_memory = state["retrieve_memory"]

        if not retrieve_rag and not retrieve_memory:
            self.logger.info(
                "Rewrite query node skipped id=%s user_id=%s "
                "reason=no_retrieval",
                state["conversation_id"],
                state["user_id"],
            )
            return {
                "rewritten_query": state["query"],
                "memory_queries": [],
            }

        self.logger.info(
            "Rewrite query node started id=%s user_id=%s "
            "retrieve_rag=%s retrieve_memory=%s",
            state["conversation_id"],
            state["user_id"],
            retrieve_rag,
            retrieve_memory,
        )
        recent_history = state["conversation_history"][-3:]
        prompt = rewrite_query_prompt(
            query=state["query"],
            conversation_summary=state["conversation_summary"],
            recent_history=recent_history,
            retrieve_rag=retrieve_rag,
            retrieve_memory=retrieve_memory,
        )
        try:
            result: RewriteQueryResponse = (
                await self.model.with_structured_output(
                    RewriteQueryResponse
                ).ainvoke(prompt)
            )
        except Exception:
            self.logger.exception(
                "Rewrite query node failed id=%s user_id=%s",
                state["conversation_id"],
                state["user_id"],
            )
            fallback_queries: list[MemoryRetrievalQuery] = []
            if retrieve_memory:
                fallback_queries = [
                    MemoryRetrievalQuery(
                        content=state["query"],
                        category="personal",
                    )
                ]
            return {
                "rewritten_query": state["query"],
                "memory_queries": fallback_queries,
            }

        rewritten = state["query"]
        if retrieve_rag:
            rewritten = (result.rag_query or "").strip() or state["query"]

        memory_queries: list[MemoryRetrievalQuery] = []
        if retrieve_memory:
            memory_queries = list(result.memory_queries)

        self.logger.info(
            "Rewrite query node completed id=%s user_id=%s original=%r "
            "rewritten=%r memory_queries=%s",
            state["conversation_id"],
            state["user_id"],
            state["query"],
            rewritten,
            len(memory_queries),
        )
        return {
            "rewritten_query": rewritten,
            "memory_queries": memory_queries,
        }


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
        )

        self.logger.info(
            "Retrieve documents node completed user_id=%s count=%s",
            state["user_id"],
            len(results),
        )
        return {"rag_documents": results}


class RetrieveMemoryNode():
    def __init__(
        self,
        memory_service: MemoryService,
        user_repository: UserRepository,
        logger: Logger,
    ):
        self.memory_service = memory_service
        self.user_repository = user_repository
        self.logger = logger

    async def __call__(self, state: AgentState) -> AgentState:
        student_name = state.get("student_name")
        student_gender = state.get("student_gender")
        need_profile = not student_name or not student_gender
        turn_queries = (
            list(state.get("memory_queries") or [])
            if state.get("retrieve_memory")
            else []
        )

        if not turn_queries and not need_profile:
            self.logger.info(
                "Retrieve memory node skipped user_id=%s reason=nothing_to_fetch",
                state["user_id"],
            )
            return {"memories": []}

        self.logger.info(
            "Retrieve memory node started user_id=%s turn_queries=%s "
            "need_profile=%s",
            state["user_id"],
            len(turn_queries),
            need_profile,
        )

        profile_task = None
        turn_task = None
        async with asyncio.TaskGroup() as tg:
            if need_profile:
                profile_task = tg.create_task(
                    self.user_repository.get_by_id(state["user_id"])
                )
            if turn_queries:
                turn_task = tg.create_task(
                    self.memory_service.retrieve_for_queries(
                        state["user_id"], turn_queries
                    )
                )

        by_id: dict[str, Memory] = {}
        if profile_task is not None:
            user = profile_task.result()
            if user is not None:
                if not student_name:
                    student_name = user.name
                if not student_gender:
                    student_gender = user.gender or "unknown"
        if turn_task is not None:
            for memory in turn_task.result():
                by_id[memory.id] = memory

        results = list(by_id.values())
        self.logger.info(
            "Retrieve memory node completed user_id=%s count=%s "
            "student_name=%s student_gender=%s",
            state["user_id"],
            len(results),
            bool(student_name),
            bool(student_gender),
        )
        return {
            "memories": results,
            "student_name": student_name,
            "student_gender": student_gender,
        }


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
            return {}

        if len(state["conversation_history"]) > 0:
            self.logger.info(
                "Retrieve history node skipped id=%s user_id=%s reason=history_exists",
                state["conversation_id"],
                state["user_id"],
            )
            return {}

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
            "title": results.title or "",
        }


class GenerateResponseNode():
    def __init__(self, model: ChatGoogleGenerativeAI, logger: Logger):
        self.model = model
        self.logger = logger

    async def __call__(self, state: AgentState) -> AgentState:
        memories = state.get("memories") or []
        self.logger.info(
            "Generate response node started id=%s user_id=%s documents=%s "
            "history=%s memories=%s",
            state["conversation_id"],
            state["user_id"],
            len(state["rag_documents"]),
            len(state["conversation_history"]),
            len(memories),
        )

        rag_documents = state["rag_documents"]
        if not rag_documents:
            self.logger.info(
                "No relevant context found for the query. user_id=%s",
                state["user_id"],
            )
            context = ""
        else:
            context = "\n\n".join(r.document.content for r in rag_documents)

        if memories:
            memories_text = "\n".join(
                f"- [{m.category}] {m.content}" for m in memories
            )
        else:
            memories_text = ""

        if state["retrieve_conversation_history"]:
            conversation_history = state["conversation_history"]
            conversation_summary = state["conversation_summary"]
            if conversation_summary:
                unsummarized = len(conversation_history) % SUMMARY_EVERY
                recent = conversation_history[-unsummarized:] if unsummarized else []
            else:
                recent = conversation_history[-SUMMARY_EVERY:]

            history_text = "\n\n".join(
                f"User: {chat.query}\nAssistant: {chat.response}"
                for chat in recent
            )
        else:
            history_text = ""

        prompt = chat_response_prompt(
            context=context,
            conversation_history_prompt=history_text,
            conversation_summary=state["conversation_summary"],
            query=state["query"],
            memories=memories_text,
            student_name=state.get("student_name"),
            student_gender=state.get("student_gender"),
        )

        writer = get_stream_writer()
        answer = ""
        async for chunk in self.model.astream(prompt):
            text = chunk.text
            if not text:
                continue
            writer({
                "type": "chat.response",
                "response": text,
            })
            answer += text

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

        return {
            "conversation_history": [chat],
        }


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
        prompt = title_prompt(state["query"], state["response"])
        title_response = await self.model.ainvoke(prompt)
        title = (title_response.text or "").strip().strip("\"'")[:255] or None
        if title is None:
            self.logger.warning(
                "Update title node produced empty title id=%s user_id=%s",
                state["conversation_id"],
                state["user_id"],
            )
            return {"title": None}

        writer = get_stream_writer()
        writer({
            "type": "chat.title",
            "response": title,
        })

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
        recent_exchanges = [
            f"Q: {chat.query}\nA: {chat.response[:200]}"
            for chat in conversation_history[-SUMMARY_EVERY:]
        ]

        self.logger.info(
            "Update summary node started id=%s user_id=%s",
            state["conversation_id"],
            state["user_id"],
        )

        prompt = summary_prompt(state["conversation_summary"], recent_exchanges)
        summary_response = await self.model.ainvoke(prompt)
        summary = (
            (summary_response.text or "").strip().strip("\"'")[:SUMMARY_MAX_CHARS]
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


class StoreMemoryNode:
    """Extract and store memories from recent user messages every SUMMARY_EVERY chats."""

    def __init__(self, memory_service: MemoryService, logger: Logger):
        self.memory_service = memory_service
        self.logger = logger

    async def __call__(self, state: AgentState) -> AgentState:
        if not state["conversation_history"]:
            self.logger.info(
                "Store memory node skipped id=%s user_id=%s reason=no_conversation_history",
                state["conversation_id"],
                state["user_id"],
            )
            return {}

        context = "\n".join(
            f"User: {chat.query}\n"
            for chat in state["conversation_history"][-SUMMARY_EVERY:]
        )
        self.logger.info(
            "Store memory node started id=%s user_id=%s",
            state["conversation_id"],
            state["user_id"],
        )
        try:
            await self.memory_service.store(
                user_id=state["user_id"],
                context=context,
            )
        except Exception:
            self.logger.exception(
                "Store memory node failed id=%s user_id=%s",
                state["conversation_id"],
                state["user_id"],
            )
            return {}

        self.logger.info(
            "Store memory node completed id=%s user_id=%s",
            state["conversation_id"],
            state["user_id"],
        )
        return {}


class CleanupNode:
    """Clears transient state before checkpointing."""

    def __init__(self, logger: Logger):
        self.logger = logger

    async def __call__(self, state: AgentState) -> AgentState:
        self.logger.info(
            "Cleanup node started id=%s user_id=%s",
            state["conversation_id"],
            state["user_id"],
        )
        return {
            "query": "",
            "rewritten_query": "",
            "first_message": False,
            "rag_documents": [],
            "retrieve_rag": False,
            "retrieve_conversation_history": False,
            "retrieve_memory": False,
            "memory_queries": [],
            "memories": [],
            "response": "",
            "messages": [],
        }
