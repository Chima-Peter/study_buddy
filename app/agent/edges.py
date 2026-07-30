from app.agent.state import SUMMARY_EVERY, AgentState


def create_conversation_router(state: AgentState) -> list[str]:
    if state["conversation_id"] is None:
        return ["create_conversation"]
    return ["retrieve_documents", "retrieve_conversation_history"]


def update_title_router(state: AgentState) -> list[str]:
    if state["first_message"]:
        return ["update_title"]
    return ["END"]


def update_summary_router(state: AgentState) -> list[str]:
    history_count = len(state["conversation_history"])
    if history_count > 0 and history_count % SUMMARY_EVERY == 0:
        return ["update_summary"]
    return ["END"]
