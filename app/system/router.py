from logging import Logger
from pathlib import Path
from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.authentication.schemas import UserResponse
from app.container import Container
from app.core.response import ApiResponse, BasicResponse
from app.core.security import get_current_user
from app.core.supabase import Supabase
from app.system.schemas.document import (
    ALL_ALLOWED_EXTENSIONS,
    CreateDocumentRequest,
    DocumentApiResponse,
    DocumentListApiResponse,
    PatchDocumentRequest,
    UpdateDocumentRequest,
    UploadUrlApiResponse,
    UploadUrlResponseData,
)
from app.system.service.document import DocumentService
from app.utils.errors.document import (
    DocumentCreateError,
    DuplicateDocumentHashError,
    DuplicateDocumentNameError,
    MissingUserForeignKeyError,
)

system_router = APIRouter(prefix="/system", tags=["system"])

_ALLOWED_EXT_HELP = ", ".join(sorted(ALL_ALLOWED_EXTENSIONS))


@system_router.post(
    "/documents/upload",
    response_model=UploadUrlApiResponse,
    summary="Create signed upload URL",
    description=(
        "Creates a document record and returns a signed storage URL. "
        "PUT the file bytes to `upload_url`, then call ingest. "
        f"Allowed file extensions: {_ALLOWED_EXT_HELP}."
    ),
    responses={
        200: {
            "description": "Upload URL created",
            "model": UploadUrlApiResponse,
        },
        400: {"description": "Missing or invalid file extension"},
        404: {"description": "User not found"},
        409: {"description": "Duplicate document name or hash"},
    },
)
@inject
async def create_upload_url(
    user: Annotated[UserResponse, Depends(get_current_user)],
    request: CreateDocumentRequest,
    service: DocumentService = Depends(Provide[Container.document_service]),
    supabase: Supabase = Depends(Provide[Container.async_supabase]),
    logger: Logger = Depends(Provide[Container.logger]),
) -> BasicResponse:
    try:
        file_extension = Path(request.file_name).suffix.lower()
        if file_extension not in ALL_ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Valid file name and extension is required. "
                    f"Allowed: {_ALLOWED_EXT_HELP}. Example: document.pdf"
                ),
            )
        upload = await supabase.create_upload_url(user.id, request.file_name)
        document = await service.create_document(
            request,
            user.id,
            upload["path"],
        )

        return BasicResponse(
            data=UploadUrlResponseData(
                upload_url=upload["signed_url"],
                path=upload["path"],
                document=document,
            ).model_dump(mode="json"),
            message="Upload URL created successfully",
        )
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
            "Unexpected error creating upload url user_id=%s", user.id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@system_router.get(
    "/documents/download",
    response_model=ApiResponse,
    summary="Create signed download URL",
    description="Returns a signed URL to download the stored document file.",
)
@inject
async def create_download_url(
    user: Annotated[UserResponse, Depends(get_current_user)],
    document_id: Annotated[
        str,
        Query(description="Document ID to download"),
    ],
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


@system_router.post(
    "/documents/{document_id}/ingest",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=DocumentApiResponse,
    summary="Start document ingestion",
    description=(
        "Queues the uploaded document for parsing, chunking, and embedding. "
        "Supports PDF, TXT, CSV, JSON, Word, and image formats."
    ),
)
@inject
async def start_ingestion(
    document_id: str,
    user: Annotated[UserResponse, Depends(get_current_user)],
    service: DocumentService = Depends(Provide[Container.document_service]),
    logger: Logger = Depends(Provide[Container.logger]),
) -> BasicResponse:
    try:
        document = await service.get_document_by_id(document_id, user.id)
        if not document.path:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document path not found",
            )
        document = await service.start_ingestion(document_id, user.id)
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )
    except Exception:
        logger.exception(
            "Unexpected error starting ingestion document_id=%s user_id=%s",
            document_id,
            user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )

    return BasicResponse(
        data=document.model_dump(mode="json"),
        message="Document ingestion started successfully",
        status_code=status.HTTP_202_ACCEPTED,
    )


@system_router.get(
    "/documents",
    response_model=DocumentListApiResponse,
    summary="List documents",
    description="List all documents for the authenticated user.",
)
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


@system_router.get(
    "/documents/{document_id}",
    response_model=DocumentApiResponse,
    summary="Get document",
    description="Get a single document by ID.",
)
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


@system_router.put(
    "/documents/{document_id}",
    response_model=DocumentApiResponse,
    summary="Replace document metadata",
    description="Full update of document name, description, and category.",
)
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


@system_router.patch(
    "/documents/{document_id}",
    response_model=DocumentApiResponse,
    summary="Patch document metadata",
    description="Partial update of document fields.",
)
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


@system_router.delete(
    "/documents/{document_id}",
    response_model=ApiResponse,
    summary="Delete document",
    description="Delete a document and its associated storage/vector data.",
)
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
