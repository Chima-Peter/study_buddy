import asyncio
from logging import Logger

from app.agent.chat_agent.schema import MemoryRetrieval
from app.agent.chat_agent.state import AgentState
from app.agent.chat_agent.utils import to_retrieval_query
from app.system.user.repository import UserRepository
from app.memory.schema import DOCUMENT_SCOPED_CATEGORIES, Memory, MemoryRetrievalQuery
from app.memory.service import MemoryService


class RetrieveMemoryNode:
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
        memory_queries = (
            [
                item
                if isinstance(item, MemoryRetrieval)
                else MemoryRetrieval.model_validate(item)
                for item in (state.get("memory_queries") or [])
            ]
            if state.get("retrieve_memory")
            else []
        )
        document_id = state.get("document_id")

        if not memory_queries and not need_profile:
            self.logger.info(
                "Retrieve memory node skipped user_id=%s reason=nothing_to_fetch",
                state.get("user_id"),
            )
            return {"memories": []}

        retrieval_queries = [
            to_retrieval_query(item, document_id)
            for item in memory_queries
        ]

        self.logger.info(
            "Retrieve memory node started user_id=%s queries=%s "
            "need_profile=%s document_id=%s",
            state.get("user_id"),
            [
                {"query": item.query, "category": item.category}
                for item in memory_queries
            ],
            need_profile,
            document_id,
        )

        profile_task = None
        turn_task = None
        async with asyncio.TaskGroup() as tg:
            if need_profile:
                profile_task = tg.create_task(
                    self.user_repository.get_by_id(state.get("user_id"))
                )
            if retrieval_queries:
                turn_task = tg.create_task(
                    self.memory_service.retrieve_for_queries(
                        state.get("user_id"),
                        retrieval_queries,
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
            state.get("user_id"),
            len(results),
            bool(student_name),
            bool(student_gender),
        )
        return {
            "memories": results,
            "student_name": student_name,
            "student_gender": student_gender,
        }
