from logging import Logger
from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, status

from app.authentication.schemas import UserResponse
from app.container import Container
from app.core.response import BasicResponse
from app.core.security import get_current_user
from app.system.study_cards.schema import StudyCardsGenerateApiResponse
from app.system.study_cards.service import StudyCardsService

study_cards_router = APIRouter(prefix="/study-cards", tags=["study-cards"])


@study_cards_router.post(
    "/{document_id}",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=StudyCardsGenerateApiResponse,
    summary="Generate study cards",
    description=(
        "Queues study-card generation for an owned document. "
        "Results are written asynchronously to study_cards."
    ),
)
@inject
async def generate_study_cards(
    document_id: str,
    user: Annotated[UserResponse, Depends(get_current_user)],
    service: StudyCardsService = Depends(Provide[Container.study_cards_service]),
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
            "Unexpected error queueing study cards generate "
            "document_id=%s user_id=%s",
            document_id,
            user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )

    return BasicResponse(
        data=result.model_dump(mode="json"),
        message="Study cards generation started successfully",
        status_code=status.HTTP_202_ACCEPTED,
    )
