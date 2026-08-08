from logging import Logger

from app.agent.question_bank.nodes.start import StartNode
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agent.question_bank.edges import route_from_checkpoint
from app.agent.question_bank.nodes import (
    CheckpointerNode,
    ConsolidateNode,
    CritiqueQuestionsNode,
    GenerateQuestionsNode,
    RetrieveChapterKeysNode,
    RetrieveChapterRecordsNode,
    SaveNode,
)
from app.agent.question_bank.state import QuestionBankState
from app.core.elasticsearch import Elasticsearch
from app.system.document.service import DocumentService
from app.system.question_bank.service import QuestionBankService


class QuestionBankGraph:
    def __init__(
        self,
        logger: Logger,
        document_service: DocumentService,
        elasticsearch: Elasticsearch,
        question_bank_model: ChatGoogleGenerativeAI,
        question_bank_service: QuestionBankService,
        checkpointer: AsyncPostgresSaver,
    ):
        self.logger = logger
        self.document_service = document_service
        self.elasticsearch = elasticsearch
        self.question_bank_model = question_bank_model
        self.question_bank_service = question_bank_service
        self.checkpointer = checkpointer

        graph = StateGraph(QuestionBankState)
        self._raw_graph = graph

        nodes = {
            "start": StartNode(logger=self.logger),
            "checkpointer": CheckpointerNode(logger=self.logger),
            "retrieve_chapter_keys": RetrieveChapterKeysNode(
                logger=self.logger,
                document_service=self.document_service,
            ),
            "retrieve_chapter_records": RetrieveChapterRecordsNode(
                logger=self.logger,
                elasticsearch=self.elasticsearch,
            ),
            "generate": GenerateQuestionsNode(
                logger=self.logger,
                model=self.question_bank_model,
            ),
            "critique": CritiqueQuestionsNode(
                logger=self.logger,
                model=self.question_bank_model,
            ),
            "consolidate": ConsolidateNode(logger=self.logger),
            "save": SaveNode(
                logger=self.logger,
                question_bank_service=self.question_bank_service,
            ),
        }

        for node_name, node in nodes.items():
            self._add_node(node_name, node)

        graph.add_edge(START, "start")
        graph.add_edge("start", "checkpointer")
        graph.add_conditional_edges(
            "checkpointer",
            route_from_checkpoint,
            {
                "retrieve_chapter_keys": "retrieve_chapter_keys",
                "retrieve_chapter_records": "retrieve_chapter_records",
                "generate": "generate",
                "critique": "critique",
                "consolidate": "consolidate",
                "save": "save",
                "END": END,
            },
        )

        graph.add_edge("retrieve_chapter_keys", "retrieve_chapter_records")
        graph.add_edge("retrieve_chapter_records", "checkpointer")
        graph.add_edge("generate", "checkpointer")
        graph.add_edge("critique", "checkpointer")
        graph.add_edge("consolidate", "save")
        graph.add_edge("save", END)

        self.graph = graph.compile(checkpointer=self.checkpointer)

    def start(self) -> CompiledStateGraph:
        return self.graph

    def _add_node(self, node_name: str, node) -> None:
        self._raw_graph.add_node(node_name, node)
