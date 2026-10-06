from logging import Logger
from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.container import Container
from app.core.response import BasicResponse
from app.core.security import get_current_user
from app.memory.schema import (
    DEFAULT_LIST_LIMIT,
    MAX_LIST_LIMIT,
    MemoryListApiResponse,
)
from app.memory.service import MemoryService
from app.system.user.schema import UserResponse

memory_router = APIRouter(prefix="/memories", tags=["memories"])


@memory_router.get(
    "",
    response_model=MemoryListApiResponse,
    summary="List user memories",
    description=(
        "List memories for the authenticated user, newest first, "
        f"with cursor-based pagination (max {MAX_LIST_LIMIT} per page)."
    ),
)
@inject
async def list_memories(
    user: Annotated[UserResponse, Depends(get_current_user)],
    service: MemoryService = Depends(Provide[Container.memory_service]),
    logger: Logger = Depends(Provide[Container.logger]),
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=MAX_LIST_LIMIT,
            description=f"Page size (1–{MAX_LIST_LIMIT}, default {DEFAULT_LIST_LIMIT})",
        ),
    ] = DEFAULT_LIST_LIMIT,
    cursor: Annotated[
        str | None,
        Query(description="Cursor from previous page's next_cursor"),
    ] = None,
) -> BasicResponse:
    logger.info("Processing list memories user_id=%s", user.id)
    try:
        result = await service.list_by_user(
            user.id,
            limit=limit,
            cursor=cursor,
        )
    except ValueError as e:
        if str(e) == "Invalid cursor":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid cursor",
            ) from e
        logger.exception(
            "Unexpected error listing memories user_id=%s", user.id
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        ) from e
    except Exception:
        logger.exception(
            "Unexpected error listing memories user_id=%s", user.id
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )

    logger.info(
        "Processed list memories user_id=%s count=%s",
        user.id,
        len(result.items),
    )
    return BasicResponse(
        data=result.model_dump(mode="json"),
        message="Memories retrieved successfully",
    )
