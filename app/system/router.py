from logging import Logger
from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.authentication.schemas import UserResponse
from app.container import Container
from app.core.ingest_pipeline import IngestPipeline
from app.core.response import BasicResponse
from app.core.security import get_current_user
from app.system.schemas.document import (
    CreateDocumentRequest,
    IngestDocumentRequest,
    PatchDocumentRequest,
    UpdateDocumentRequest,
    validate_upload,
)
from app.system.service.document import DocumentService
from app.utils.errors import DocumentCreateError, MissingUserForeignKeyError

system_router = APIRouter(prefix="/system", tags=["system"])


@system_router.post("/ingest-documents")
@inject
async def ingest_document(
    user: Annotated[UserResponse, Depends(get_current_user)],
    file: Annotated[UploadFile, File()],
    category: Annotated[str, Form()],
    ingest_pipeline: IngestPipeline = Depends(
        Provide[Container.ingest_pipeline_service]
    ),
) -> BasicResponse:
    validate_upload(file)

    document_payload = IngestDocumentRequest(
        filename=file.filename or "",
        category=category,
        file=file.file,
        user_id=user.id,
    )

    await ingest_pipeline.initiate_ingest_pipeline(document_payload)

    return BasicResponse(
        status_code=status.HTTP_200_OK,
        message="Documents ingested successfully",
        data={},
    )


@system_router.post("/documents", status_code=status.HTTP_201_CREATED)
@inject
async def create_document(
    request: CreateDocumentRequest,
    user: Annotated[UserResponse, Depends(get_current_user)],
    service: DocumentService = Depends(Provide[Container.document_service]),
    logger: Logger = Depends(Provide[Container.logger]),
) -> BasicResponse:
    try:
        document = await service.create_document(request, user.id)
    except MissingUserForeignKeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    except DocumentCreateError:
        logger.exception("Failed to create document user_id=%s", user.id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create document",
        )
    except Exception:
        logger.exception(
            "Unexpected error creating document user_id=%s", user.id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )

    return BasicResponse(
        data=document.model_dump(mode="json"),
        message="Document created successfully",
        status_code=status.HTTP_201_CREATED,
    )


@system_router.get("/documents")
@inject
async def list_documents(
    user: Annotated[UserResponse, Depends(get_current_user)],
    service: DocumentService = Depends(Provide[Container.document_service]),
    logger: Logger = Depends(Provide[Container.logger]),
) -> BasicResponse:
    try:
        documents = await service.get_documents_by_user_id(user.id)
    except Exception:
        logger.exception(
            "Unexpected error listing documents user_id=%s", user.id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )

    return BasicResponse(
        data=[document.model_dump(mode="json") for document in documents],
        message="Documents retrieved successfully",
    )


@system_router.get("/documents/{document_id}")
@inject
async def get_document(
    document_id: str,
    user: Annotated[UserResponse, Depends(get_current_user)],
    service: DocumentService = Depends(Provide[Container.document_service]),
    logger: Logger = Depends(Provide[Container.logger]),
) -> BasicResponse:
    try:
        document = await service.get_document_by_id(document_id, user.id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )
    except Exception:
        logger.exception(
            "Unexpected error getting document id=%s user_id=%s",
            document_id,
            user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )

    return BasicResponse(
        data=document.model_dump(mode="json"),
        message="Document retrieved successfully",
    )


@system_router.put("/documents/{document_id}")
@inject
async def update_document(
    document_id: str,
    request: UpdateDocumentRequest,
    user: Annotated[UserResponse, Depends(get_current_user)],
    service: DocumentService = Depends(Provide[Container.document_service]),
    logger: Logger = Depends(Provide[Container.logger]),
) -> BasicResponse:
    try:
        document = await service.update_document(document_id, request, user.id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )
    except Exception:
        logger.exception(
            "Unexpected error updating document id=%s user_id=%s",
            document_id,
            user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )

    return BasicResponse(
        data=document.model_dump(mode="json"),
        message="Document updated successfully",
    )


@system_router.patch("/documents/{document_id}")
@inject
async def patch_document(
    document_id: str,
    request: PatchDocumentRequest,
    user: Annotated[UserResponse, Depends(get_current_user)],
    service: DocumentService = Depends(Provide[Container.document_service]),
    logger: Logger = Depends(Provide[Container.logger]),
) -> BasicResponse:
    try:
        document = await service.patch_document(document_id, request, user.id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )
    except Exception:
        logger.exception(
            "Unexpected error patching document id=%s user_id=%s",
            document_id,
            user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )

    return BasicResponse(
        data=document.model_dump(mode="json"),
        message="Document patched successfully",
    )


@system_router.delete("/documents/{document_id}")
@inject
async def delete_document(
    document_id: str,
    user: Annotated[UserResponse, Depends(get_current_user)],
    service: DocumentService = Depends(Provide[Container.document_service]),
    logger: Logger = Depends(Provide[Container.logger]),
) -> BasicResponse:
    try:
        await service.delete_document(document_id, user.id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )
    except Exception:
        logger.exception(
            "Unexpected error deleting document id=%s user_id=%s",
            document_id,
            user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )

    return BasicResponse(message="Document deleted successfully")
