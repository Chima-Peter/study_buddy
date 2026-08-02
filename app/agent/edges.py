from app.agent.schema import SUMMARY_EVERY
from app.agent.state import AgentState


def update_title_router(state: AgentState) -> list[str]:
    if state["first_message"]:
        return ["update_title"]
    return ["cleanup"]


def update_summary_router(state: AgentState) -> list[str]:
    history_count = len(state["conversation_history"])
    if history_count > 0 and history_count % SUMMARY_EVERY == 0:
        return ["update_summary", "store_memory"]
    return ["store_memory"]
