from typing import IO, Annotated, Optional

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, File, Form, UploadFile, status

from app.authentication.schemas import UserResponse
from app.container import Container
from app.core.ingest_pipeline import IngestPipeline
from app.core.response import BasicResponse
from app.core.security import get_current_user
from app.system.schemas.ingest_pipeline import (
    FileType,
    validate_upload,
)

system_router = APIRouter(prefix="/system", tags=["system"])


@system_router.post("/ingest-documents")
@inject
async def ingest_document(
    user: Annotated[UserResponse, Depends(get_current_user)],
    files: Annotated[list[UploadFile], File()],
    ingest_pipeline: IngestPipeline = Depends(
        Provide[Container.ingest_pipeline_service]),
    file_type: Annotated[Optional[FileType], Form()] = None,
) -> BasicResponse:
    for file in files:
        validate_upload(file, file_type)

    data: dict[str, IO[bytes]] = {}
    for file in files:
        data[file.filename] = file.file

    await ingest_pipeline.initiate_ingest_pipeline(data, user.id)

    return BasicResponse(
        status_code=status.HTTP_200_OK,
        message="Documents ingested successfully",
        data={},
    )
