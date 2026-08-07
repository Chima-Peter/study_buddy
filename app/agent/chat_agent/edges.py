from app.agent.chat_agent.schema import SUMMARY_EVERY
from app.agent.chat_agent.state import AgentState


def update_title_router(state: AgentState) -> list[str]:
    if state["first_message"]:
        return ["update_title"]
    return ["cleanup"]


def update_summary_router(state: AgentState) -> list[str]:
    if state.get("is_academic_discussion", True):
        history_count = len(state.get("conversation_history") or [])
        if history_count > 0 and history_count % SUMMARY_EVERY == 0:
            return ["update_summary", "store_memory"]
        return ["store_memory"]
    return ["cleanup"]

def decide_retrieval_router(state: AgentState) -> list[str]:
    if not state.get("is_academic_discussion", True):
        return ["end_discussion"]
    return ["rewrite_query", "retrieve_conversation_history"]
