from logging import Logger

from app.agent.study_cards_agent.nodes.retrieval.retrieve_memories import RetrieveMemoriesNode
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agent.study_cards_agent.edges import route_from_checkpoint
from app.agent.study_cards_agent.nodes import (
    CheckpointerNode,
    ConsolidateNode,
    CritiqueNode,
    GenerateChapterNode,
    RetrieveChaptersNode,
    RetrieveSessionsNode,
    SaveNode,
)
from app.agent.study_cards_agent.state import StudyCardsState
from app.core.elasticsearch import Elasticsearch
from app.system.document.service import DocumentService
from app.system.study_cards import StudyCardsService


class StudyCardsGraph:
    def __init__(
        self,
        logger: Logger,
        document_service: DocumentService,
        elasticsearch: Elasticsearch,
        chat_model: ChatGoogleGenerativeAI,
        study_cards_service: StudyCardsService,
        checkpointer: AsyncPostgresSaver,
    ):
        self.logger = logger
        self.document_service = document_service
        self.elasticsearch = elasticsearch
        self.chat_model = chat_model
        self.study_cards_service = study_cards_service
        self.checkpointer = checkpointer

        graph = StateGraph(StudyCardsState)
        self._raw_graph = graph

        nodes = {
            "checkpointer": CheckpointerNode(logger=self.logger),
            "retrieve_chapter_keys": RetrieveChaptersNode(
                logger=self.logger,
                document_service=self.document_service,
            ),
            "retrieve_sessions": RetrieveSessionsNode(
                logger=self.logger,
                elasticsearch=self.elasticsearch,
            ),
            "retrieve_memories": RetrieveMemoriesNode(
                logger=self.logger,
                memory_service=self.memory_service,
            ),
            "generate": GenerateChapterNode(
                logger=self.logger,
                model=self.chat_model,
            ),
            "critique": CritiqueNode(
                logger=self.logger,
                model=self.chat_model,
            ),
            "consolidate": ConsolidateNode(logger=self.logger),
            "save": SaveNode(
                logger=self.logger,
                study_card_service=self.study_cards_service,
            ),
        }

        for node_name, node in nodes.items():
            self._add_node(node_name, node)

        graph.add_edge(START, "checkpointer")
        graph.add_conditional_edges(
            "checkpointer",
            route_from_checkpoint,
            {
                "retrieve_memories": "retrieve_memories",
                "retrieve_chapter_keys": "retrieve_chapter_keys",
                "retrieve_sessions": "retrieve_sessions",
                "generate": "generate",
                "critique": "critique",
                "consolidate": "consolidate",
                "save": "save",
                "END": END,
            },
        )
        graph.add_edge("retrieve_memories", "retrieve_chapter_keys")
        graph.add_edge("retrieve_chapter_keys", "retrieve_sessions")
        graph.add_edge("retrieve_sessions", "checkpointer")
        graph.add_edge("generate", "checkpointer")
        graph.add_edge("critique", "checkpointer")
        graph.add_edge("consolidate", "save")
        graph.add_edge("save", END)

        self.graph = graph.compile(checkpointer=self.checkpointer)

    def start(self) -> CompiledStateGraph:
        return self.graph

    def _add_node(self, node_name: str, node) -> None:
        self._raw_graph.add_node(node_name, node)
