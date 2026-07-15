from logging import Logger
from pathlib import Path
from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.authentication.schemas import UserResponse
from app.container import Container
from app.core.response import BasicResponse
from app.core.security import get_current_user
from app.core.supabase import Supabase
from app.system.schemas.document import (
    CreateDocumentRequest,
    PatchDocumentRequest,
    UpdateDocumentRequest,
)
from app.system.service.document import DocumentService
from app.utils.errors.document import (
    DocumentCreateError,
    DuplicateDocumentHashError,
    DuplicateDocumentNameError,
    MissingUserForeignKeyError,
)

system_router = APIRouter(prefix="/system", tags=["system"])


@system_router.get("/documents/upload")
@inject
async def create_upload_url(
    user: Annotated[UserResponse, Depends(get_current_user)],
    file_name: Annotated[str, Query()],
    supabase: Supabase = Depends(Provide[Container.async_supabase]),
    logger: Logger = Depends(Provide[Container.logger]),
) -> BasicResponse:
    try:
        file_extension = Path(file_name).suffix
        if file_extension is None or file_extension == "":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Valid file name and extension is required. Example: document.pdf",
            )
        upload_url = await supabase.create_upload_url(user.id, file_name)
    except Exception:
        logger.exception(
            "Unexpected error creating upload url user_id=%s", user.id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )

    return BasicResponse(
        data=upload_url,
        message="Upload URL created successfully",
    )


@system_router.get("/documents/download")
@inject
async def create_download_url(
    user: Annotated[UserResponse, Depends(get_current_user)],
    document_id: Annotated[str, Query()],
    document_service: DocumentService = Depends(
        Provide[Container.document_service]),
    supabase: Supabase = Depends(Provide[Container.async_supabase]),
    logger: Logger = Depends(Provide[Container.logger]),
) -> BasicResponse:
    try:
        document = await document_service.get_document_by_id(document_id, user.id)
        if document.path is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document path not found",
            )
        download_url = await supabase.create_download_url(document.path)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )
    except Exception:
        logger.exception(
            "Unexpected error creating upload url user_id=%s", user.id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )

    return BasicResponse(
        data=download_url,
        message="Download URL created successfully",
    )


@system_router.post("/documents", status_code=status.HTTP_201_CREATED)
@inject
async def create_document(
    request: CreateDocumentRequest,
    user: Annotated[UserResponse, Depends(get_current_user)],
    supabase: Supabase = Depends(Provide[Container.async_supabase]),
    service: DocumentService = Depends(Provide[Container.document_service]),
    logger: Logger = Depends(Provide[Container.logger]),
) -> BasicResponse:
    try:
        file_extension = Path(request.path).suffix
        if file_extension is None or file_extension == "":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Valid file name and extension is required. Example: document.pdf",
            )

        if not await supabase.verify_file(f"{user.id}/{request.file_name}"):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="File not found. Upload the file first to the system",
            )
        document = await service.create_document(request, user.id)
    except HTTPException:
        raise
    except MissingUserForeignKeyError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except DuplicateDocumentNameError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )
    except DuplicateDocumentHashError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )
    except DocumentCreateError as e:
        logger.exception("Failed to create document user_id=%s", user.id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
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
