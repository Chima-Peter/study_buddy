from logging import Logger

from langchain_core.messages import AIMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.config import get_stream_writer

from app.agent.chat_agent.messages import format_history
from app.agent.chat_agent.prompts import chat_response_prompt
from app.agent.chat_agent.schema import SUMMARY_EVERY
from app.agent.chat_agent.state import AgentState
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
            state["conversation_id"],
            state["user_id"],
            len(state["rag_documents"]),
            len(messages),
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
            history_text = format_history(messages, limit=SUMMARY_EVERY)
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
        try:
            async for chunk in self.model.astream(prompt):
                text = chunk.text
                if not text:
                    continue
                writer({
                    "type": "chat.response",
                    "response": text,
                })
                answer += text
        except Exception as e:
            if is_rate_limit_error(e):
                self.logger.warning(
                    "Generate response node rate limited id=%s user_id=%s",
                    state["conversation_id"],
                    state["user_id"],
                )
                writer({
                    "type": "chat.response",
                    "response": "I'm sorry, I'm experiencing a technical issue. Please try again later.",
                })
            else:
                self.logger.exception(
                    "Generate response node failed id=%s user_id=%s",
                    state["conversation_id"],
                    state["user_id"],
                )
            raise

        self.logger.info(
            "Generate response node completed id=%s user_id=%s response_chars=%s",
            state["conversation_id"],
            state["user_id"],
            len(answer),
        )
        return {
            "response": answer,
            "messages": [AIMessage(content=answer)],
        }
