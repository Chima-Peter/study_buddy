from logging import Logger
from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, status

from app.authentication.schemas import UserResponse
from app.container import Container
from app.core.response import BasicResponse
from app.core.security import get_current_user
from app.system.schemas.chat import QueryApiResponse, QueryRequest
from app.system.service.chat import ChatService

chat_router = APIRouter(prefix="/chat", tags=["chat"])


@chat_router.post(
    "/query",
    response_model=QueryApiResponse,
    summary="Query documents",
    description=(
        "Embeds the query, searches Elasticsearch, then runs the RAG retriever "
        "to produce an answer with source chunks."
    ),
)
@inject
async def query_documents(
    request: QueryRequest,
    user: Annotated[UserResponse, Depends(get_current_user)],
    service: ChatService = Depends(Provide[Container.chat_service]),
    logger: Logger = Depends(Provide[Container.logger]),
) -> BasicResponse:
    try:
        result = await service.query(
            user.id,
            request.query,
            top_k=request.top_k,
            mode=request.mode,
        )
    except Exception:
        logger.exception(
            "Unexpected error querying documents user_id=%s", user.id
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )

    return BasicResponse(
        data=result.model_dump(mode="json"),
        message="Query completed successfully",
    )
