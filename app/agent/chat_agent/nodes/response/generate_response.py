from logging import Logger

from langchain_core.messages import AIMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.config import get_stream_writer

from app.agent.chat_agent.prompts import chat_response_prompt
from app.agent.chat_agent.schema import SUMMARY_EVERY
from app.agent.chat_agent.state import AgentState
from app.agent.chat_agent.utils import format_history, format_rag_context, pick_progress
from app.utils.llm import is_rate_limit_error


class GenerateResponseNode:
    def __init__(self, model: ChatGoogleGenerativeAI, logger: Logger):
        self.model = model
        self.logger = logger

    async def __call__(self, state: AgentState) -> AgentState:
        memories = state.get("memories") or []
        messages = state.get("messages") or []
        self.logger.info(
            "Generate response node started id=%s user_id=%s documents=%s "
            "messages=%s memories=%s",
            state.get("conversation_id"),
            state.get("user_id"),
            len(state.get("rag_documents") or []),
            len(messages),
            len(memories),
        )

        rag_documents = state.get("rag_documents")
        if not rag_documents:
            self.logger.info(
                "No relevant context found for the query. user_id=%s",
                state.get("user_id"),
            )
            context = ""
        else:
            context = format_rag_context(rag_documents)

        if memories:
            memories_text = "\n".join(
                f"- [{m.category}] {m.content}" for m in memories
            )
        else:
            memories_text = ""

        answer_from_history = bool(state.get("answer_from_history"))
        if state.get("retrieve_conversation_history") or answer_from_history:
            history_text = format_history(messages, limit=SUMMARY_EVERY)
        else:
            history_text = ""

        tavily_hits = state.get("tavily_results") or []
        if tavily_hits and not answer_from_history:
            link_lines: list[str] = []
            for hit in tavily_hits[:5]:
                if not isinstance(hit, dict):
                    continue
                title = (hit.get("title") or "").strip() or "Resource"
                url = (hit.get("url") or "").strip()
                content = (hit.get("content") or "").strip()
                if not url:
                    continue
                link_lines.append(f"- [{title}]: {url} -- {content}")
            tavily_text = "\n".join(link_lines)
        else:
            tavily_text = ""

        prompt = chat_response_prompt(
            context=context,
            conversation_history_prompt=history_text,
            conversation_summary=state.get("conversation_summary"),
            query=state.get("query"),
            memories=memories_text,
            student_name=state.get("student_name"),
            student_gender=state.get("student_gender"),
            tavily_results=tavily_text,
            answer_from_history=answer_from_history,
        )

        writer = get_stream_writer()
        writer({
            "type": "chat.progress",
            "message": pick_progress(
                "generate_history" if answer_from_history else "generate"
            ),
            "conversation_id": state.get("conversation_id"),
        })
        answer = ""
        try:
            async for chunk in self.model.astream(prompt):
                text = chunk.text
                if not text:
                    continue
                writer({
                    "type": "chat.response",
                    "response": text,
                    "conversation_id": state.get("conversation_id"),
                })
                answer += text
        except Exception as e:
            if is_rate_limit_error(e):
                self.logger.warning(
                    "Generate response node rate limited id=%s user_id=%s",
                    state.get("conversation_id"),
                    state.get("user_id"),
                )
                writer({
                    "type": "chat.error",
                    "response": "I'm sorry, I'm experiencing a technical issue. Please try again later.",
                    "conversation_id": state.get("conversation_id"),
                })
                response = "I'm sorry, I'm experiencing a technical issue. Please try again later."
                return {
                    "response": response,
                    "messages": [AIMessage(content=response)],
                }
            else:
                self.logger.exception(
                    "Generate response node failed id=%s user_id=%s",
                    state.get("conversation_id"),
                    state.get("user_id"),
                )
                raise

        self.logger.info(
            "Generate response node completed id=%s user_id=%s response_chars=%s",
            state.get("conversation_id"),
            state.get("user_id"),
            len(answer),
        )
        return {
            "response": answer,
            "messages": [AIMessage(content=answer)],
        }
