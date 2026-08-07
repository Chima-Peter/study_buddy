from app.agent.chat_agent.state import AgentState


def decide_retrieval_router(state: AgentState) -> list[str]:
    if not state.get("is_academic_discussion", True):
        return ["end_discussion"]
    return ["rewrite_query", "retrieve_conversation_history"]
