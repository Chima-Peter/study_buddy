import asyncio
from logging import Logger

from app.agent.chat_agent.state import AgentState
from app.authentication.repository.user_repository import UserRepository
from app.memory.schema import Memory, MemoryRetrievalQuery
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
        memory_query = (
            state.get("memory_query")
            if state.get("retrieve_memory")
            else None
        )

        if not memory_query and not need_profile:
            self.logger.info(
                "Retrieve memory node skipped user_id=%s reason=nothing_to_fetch",
                state["user_id"],
            )
            return {"memories": []}

        self.logger.info(
            "Retrieve memory node started user_id=%s has_query=%s "
            "need_profile=%s",
            state["user_id"],
            bool(memory_query),
            need_profile,
        )

        profile_task = None
        turn_task = None
        async with asyncio.TaskGroup() as tg:
            if need_profile:
                profile_task = tg.create_task(
                    self.user_repository.get_by_id(state["user_id"])
                )
            if memory_query:
                turn_task = tg.create_task(
                    self.memory_service.retrieve_for_queries(
                        state["user_id"],
                        [MemoryRetrievalQuery(content=memory_query)],
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
            state["user_id"],
            len(results),
            bool(student_name),
            bool(student_gender),
        )
        return {
            "memories": results,
            "student_name": student_name,
            "student_gender": student_gender,
        }
