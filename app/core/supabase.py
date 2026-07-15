from logging import Logger
from typing import IO

import httpx
import uuid_utils
from supabase import AsyncClient


class Supabase:
    def __init__(self, supabase: AsyncClient, logger: Logger):
        self.supabase = supabase
        self.logger = logger

    async def create_upload_url(self, user_id, file_name: str) -> dict[str, str]:
        storage_path = f"{user_id}/{uuid_utils.uuid4()}-{file_name}"
        response = await self.supabase.storage.from_("documents").create_signed_upload_url(
            path=storage_path,
        )

        self.logger.info(f"Generated upload URL for {storage_path}")
        return {
            "signed_url": response["signed_url"],
            "path": response["path"],
        }

    async def create_download_url(self, path: str) -> str:
        response = await self.supabase.storage.from_("documents").create_signed_url(
            path=path,
            expires_in=600,
        )

        self.logger.info(f"Generated download URL for {path}")
        return response["signedUrl"]

    async def delete_file(self, path: str) -> dict[str, str]:
        response = await self.supabase.storage.from_("documents").remove(
            paths=[path],
        )

        self.logger.info(f"Deleted file {path}")
        return response

    async def download_file(self, path: str) -> bytes:
        response = await self.supabase.storage.from_("documents").download(
            path=path,
        )

        self.logger.info(f"Downloaded file {path}")
        return response

    async def download_file_to(self, path: str, destination: IO[bytes]) -> None:
        """Stream storage object to destination in chunks (constant memory)."""
        url = await self.create_download_url(path)
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    if chunk:
                        destination.write(chunk)

        self.logger.info(f"Streamed file {path} to destination")

    async def upload_file(self, path: str, file: IO[bytes], content_type: str) -> dict[str, str]:
        response = await self.supabase.storage.from_("documents").upload(
            path=path,
            file=file,
            file_options={
                "content-type": content_type,
                "upsert": False,
            }
        )

        self.logger.info(f"Uploaded file {path}")
        return response
