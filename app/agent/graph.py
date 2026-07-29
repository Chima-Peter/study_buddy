from langgraph.graph.state import CompiledStateGraph
from app.agent.nodes import (
    CreateConversationNode,
    GenerateResponseNode,
    RetrieveConversationHistoryNode,
    RetrieveDocumentsNode,
    SaveChatNode,
    UpdateConversationSummaryNode,
    UpdateConversationTitleNode,
)
from app.agent.state import AgentState
from langgraph.graph import START, StateGraph, END
from logging import Logger
from app.rag.retriever import RAGRetriever
from app.system.service.chat import ChatService
from app.system.service.conversation import ConversationService

class AgentGraph:
    def __init__(
        self,
        retriever: RAGRetriever,
        conversation_service: ConversationService,
        chat_service: ChatService,
        logger: Logger,
    ):
        self.retriever = retriever
        self.conversation_service = conversation_service
        self.chat_service = chat_service
        self.logger = logger
        graph = StateGraph(AgentState)

        graph.add_node("create_conversation", CreateConversationNode(
            conversation_service=self.conversation_service,
            logger=self.logger,
        ))
        graph.add_node("retrieve_documents", RetrieveDocumentsNode(
            retriever=self.retriever,
            logger=self.logger,
        ))
        graph.add_node("retrieve_conversation_history", RetrieveConversationHistoryNode(
            conversation_service=self.conversation_service,
            logger=self.logger,
        ))
        graph.add_node("generate_response", GenerateResponseNode(
            retriever=self.retriever,
            logger=self.logger,
        ))
        graph.add_node("save_chat", SaveChatNode(
            chat_service=self.chat_service,
            logger=self.logger,
        ))
        graph.add_node("update_conversation_title", UpdateConversationTitleNode(
            conversation_service=self.conversation_service,
            model=self.retriever.model,
            logger=self.logger,
        ))
        graph.add_node("update_conversation_summary", UpdateConversationSummaryNode(
            conversation_service=self.conversation_service,
            model=self.retriever.model,
            logger=self.logger,
        ))

        graph.add_edge(START, "create_conversation")
        graph.add_edge("create_conversation", "retrieve_documents")
        graph.add_edge("create_conversation", "retrieve_conversation_history")
        graph.add_edge("retrieve_documents", "generate_response")
        graph.add_edge("retrieve_conversation_history", "generate_response")
        graph.add_edge("generate_response", "save_chat")
        graph.add_edge("generate_response", "update_conversation_title")
        graph.add_edge("save_chat", "update_conversation_summary")
        graph.add_edge("update_conversation_title", END)
        graph.add_edge("update_conversation_summary", END)

        self.graph = graph.compile()

    def start(self) -> CompiledStateGraph:
        return self.graph