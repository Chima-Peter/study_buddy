from datetime import datetime, timezone
from logging import Logger

from app.system.user.model import UserModel
from app.system.user.repository import UserRepository
from app.system.user.schema import UpdateProfileRequest, UserResponse
from app.core.elasticsearch import Elasticsearch
from app.core.supabase import Supabase
from app.utils.errors import DuplicateEmailError, EmailAlreadyExistsError, UserNotFoundError


class UserService:
    """User profile and account business logic."""

    def __init__(
        self,
        repository: UserRepository,
        logger: Logger,
        elasticsearch: Elasticsearch,
        supabase: Supabase,
    ):
        self.repository = repository
        self._logger = logger
        self.elasticsearch = elasticsearch
        self.supabase = supabase

    async def get_user(self, email: str) -> UserResponse | None:
        user = await self.repository.get_by_email(email)
        if user is None:
            return None
        return self._to_response(user)

    async def get_user_by_id(self, user_id: str) -> UserResponse | None:
        user = await self.repository.get_by_id(user_id)
        if user is None:
            return None
        return self._to_response(user)

    async def update_profile(
        self,
        user_id: str,
        request: UpdateProfileRequest,
    ) -> UserResponse:
        user = await self.repository.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError(user_id)

        if "name" in request.model_fields_set and request.name is not None:
            user.name = request.name
        if "gender" in request.model_fields_set:
            user.gender = request.gender
        if "university" in request.model_fields_set:
            user.university = request.university
        if "bio" in request.model_fields_set:
            user.bio = request.bio
        if "timezone" in request.model_fields_set:
            user.timezone = request.timezone

        user.updated_at = datetime.now(timezone.utc)

        try:
            updated = await self.repository.update(user)
        except DuplicateEmailError as e:
            self._logger.warning(
                "Profile update failed - email exists: %s", user.email
            )
            raise EmailAlreadyExistsError(user.email) from e

        self._logger.info("Profile updated user_id=%s", user_id)
        return self._to_response(updated)

    async def delete_account(self, user_id: str) -> None:
        user = await self.repository.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError(user_id)

        document_paths = await self.repository.list_document_paths(user_id)

        try:
            deleted_docs = await self.elasticsearch.delete_by_user(
                user_id, index="documents"
            )
            deleted_memories = await self.elasticsearch.delete_by_user(
                user_id, index="user_memories"
            )
            self._logger.info(
                "Account ES cleanup user_id=%s documents=%s memories=%s",
                user_id,
                deleted_docs,
                deleted_memories,
            )
        except Exception:
            self._logger.exception(
                "Account ES cleanup failed user_id=%s", user_id
            )

        for path in document_paths:
            try:
                await self.supabase.delete_file(path)
            except Exception:
                self._logger.exception(
                    "Account storage cleanup failed user_id=%s path=%s",
                    user_id,
                    path,
                )

        deleted = await self.repository.delete(user_id)
        if not deleted:
            raise UserNotFoundError(user_id)

        self._logger.info("Account deleted user_id=%s", user_id)

    def _to_response(self, user: UserModel) -> UserResponse:
        return UserResponse(
            id=user.id,
            name=user.name,
            email=user.email,
            gender=user.gender,
            university=user.university,
            bio=user.bio,
            timezone=user.timezone,
            created_at=user.created_at,
            updated_at=user.updated_at,
        )
