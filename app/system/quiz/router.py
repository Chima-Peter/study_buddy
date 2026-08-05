from logging import Logger
from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, status

from app.authentication.schemas import UserResponse
from app.container import Container
from app.core.response import BasicResponse
from app.core.security import get_current_user
from app.system.quiz.schema import QuizGenerateApiResponse
from app.system.quiz.service import QuizService

quiz_router = APIRouter(prefix="/quiz", tags=["quiz"])


@quiz_router.post(
    "/{document_id}",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=QuizGenerateApiResponse,
    summary="Generate quiz and study cards",
    description=(
        "Queues quiz and study-card generation for an owned document. "
        "Results are written asynchronously to quiz_results."
    ),
)
@inject
async def generate_quiz(
    document_id: str,
    user: Annotated[UserResponse, Depends(get_current_user)],
    service: QuizService = Depends(Provide[Container.quiz_service]),
    logger: Logger = Depends(Provide[Container.logger]),
) -> BasicResponse:
    try:
        result = await service.enqueue_generate(document_id, user.id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )
    except Exception:
        logger.exception(
            "Unexpected error queueing quiz generate document_id=%s user_id=%s",
            document_id,
            user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )

    return BasicResponse(
        data=result.model_dump(mode="json"),
        message="Quiz generation started successfully",
        status_code=status.HTTP_202_ACCEPTED,
    )
