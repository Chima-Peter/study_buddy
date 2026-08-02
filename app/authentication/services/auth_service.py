from datetime import datetime, timezone
from logging import Logger

from app.authentication.models.user import UserModel
from app.authentication.repository.user_repository import UserRepository
from app.authentication.schemas import LoginRequest, RegisterRequest
from app.authentication.schemas.auth import (
    LoginResponse,
    UpdateProfileRequest,
    UserResponse,
)
from app.config import Settings
from app.core.elasticsearch import Elasticsearch
from app.core.redis import RedisClient
from app.core.supabase import Supabase
from app.utils.bcrypt import hash_password, verify_password
from app.utils.errors import DuplicateEmailError, EmailAlreadyExistsError, UserNotFoundError
from app.utils.errors.auth import InvalidCredentialsError
from app.utils.jwt import decode_token, generate_token

BLACKLIST_PREFIX = "blacklist:"


class AuthService:
    """Authentication business logic."""

    def __init__(
        self,
        repository: UserRepository,
        redis: RedisClient,
        settings: Settings,
        logger: Logger,
        elasticsearch: Elasticsearch,
        supabase: Supabase,
    ):
        self.repository = repository
        self.redis = redis
        self.settings = settings
        self._logger = logger
        self.elasticsearch = elasticsearch
        self.supabase = supabase

    async def register(self, request: RegisterRequest) -> LoginResponse:
        """Register a new user and issue a JWT token."""
        self._logger.info("Register attempt email=%s", request.email)
        try:
            password_hash = hash_password(request.password)
            user = UserModel(
                name=request.name,
                email=request.email,
                hashed_password=password_hash,
            )
            user = await self.repository.create(user)
            token = self._issue_token(user)
            self._logger.info("Register success user_id=%s email=%s", user.id, user.email)
            return LoginResponse(
                user=self._to_response(user),
                token=token,
            )
        except DuplicateEmailError as e:
            self._logger.warning("Register failed - email exists: %s", request.email)
            raise EmailAlreadyExistsError(request.email) from e

    async def login(self, request: LoginRequest) -> LoginResponse:
        self._logger.info("Login attempt email=%s", request.email)
        user = await self.repository.get_by_email(request.email)
        if user is None:
            self._logger.warning("Login failed - user not found: %s", request.email)
            raise UserNotFoundError(request.email)

        if not verify_password(request.password, user.hashed_password):
            self._logger.warning("Login failed - invalid password: %s", request.email)
            raise InvalidCredentialsError(request.email)

        token = self._issue_token(user)
        self._logger.info("Login success user_id=%s email=%s", user.id, user.email)
        return LoginResponse(
            user=self._to_response(user),
            token=token,
        )

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
        if "email" in request.model_fields_set and request.email is not None:
            user.email = request.email
        if "password" in request.model_fields_set and request.password is not None:
            user.hashed_password = hash_password(request.password)
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
                "Profile update failed - email exists: %s", request.email
            )
            raise EmailAlreadyExistsError(str(request.email)) from e

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

    async def logout(self, token: str) -> None:
        """Blacklist a token in Redis until it would have expired."""
        payload = decode_token(
            token, self.settings.jwt_secret, self.settings.jwt_algorithm
        )
        user_id = payload.get("sub")
        expires_at = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        ttl = int((expires_at - datetime.now(timezone.utc)).total_seconds())
        if ttl > 0:
            await self.redis.set(f"{BLACKLIST_PREFIX}{token}", "1", ttl)
            self._logger.info("Logout success user_id=%s", user_id)

    async def is_blacklisted(self, token: str) -> bool:
        return await self.redis.exists(f"{BLACKLIST_PREFIX}{token}")

    def _issue_token(self, user: UserModel) -> str:
        return generate_token(
            subject=str(user.id),
            secret=self.settings.jwt_secret,
            algorithm=self.settings.jwt_algorithm,
            expire_minutes=self.settings.jwt_expire_minutes,
        )

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
