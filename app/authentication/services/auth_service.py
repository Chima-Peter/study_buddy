import uuid
from datetime import datetime, timezone

from app.authentication.models.user import UserModel
from app.authentication.repository.user_repository import UserRepository
from app.authentication.schemas import LoginRequest, RegisterRequest
from app.authentication.schemas.auth import LoginResponse, UserResponse
from app.config import Settings
from app.core.redis import RedisClient
from app.utils.bcrypt import hash_password, verify_password
from app.utils.errors import DuplicateEmailError, EmailAlreadyExistsError, UserNotFoundError
from app.utils.errors.auth import InvalidCredentialsError
from app.utils.jwt import decode_token, generate_token

BLACKLIST_PREFIX = "blacklist:"


class AuthService:
    """Authentication business logic.

    Face-id verification will gate token issuance later; for now login is a
    normal email lookup that issues a JWT directly.
    """

    def __init__(
        self, repository: UserRepository, redis: RedisClient, settings: Settings
    ):
        self.repository = repository
        self.redis = redis
        self.settings = settings

    async def register(self, request: RegisterRequest) -> LoginResponse:
        """Register a new user and issue a JWT token."""
        try:
            password_hash = hash_password(request.password)
            user = UserModel(
              name=request.name,
              email=request.email,
              password_hash=password_hash,
            )
            user = await self.repository.create(user)
            token = self._issue_token(user)
            return LoginResponse(
              id=user.id,
              name=user.name,
              email=user.email,
              created_at=user.created_at,
              updated_at=user.updated_at,
              token=token,
            )
        except DuplicateEmailError as e:
            raise EmailAlreadyExistsError(user.email) from e

    async def login(self, request: LoginRequest) -> LoginResponse:
        user = await self.repository.get_by_email(request.email)
        if user is None:
            raise UserNotFoundError(request.email)

        if not verify_password(request.password, user.hashed_password):
          raise InvalidCredentialsError(request.email)
        token = self._issue_token(user)
        return LoginResponse(
              id=user.id,
              name=user.name,
              email=user.email,
              created_at=user.created_at,
              updated_at=user.updated_at,
              token=token,
            )

    async def get_user(self, email: str) -> UserResponse:
        user = await self.repository.get_by_email(email)
        if user is None:
            raise UserNotFoundError(email)
        return UserResponse(
              id=user.id,
              name=user.name,
              email=user.email,
              created_at=user.created_at,
              updated_at=user.updated_at,
            )

    async def logout(self, token: str) -> None:
        """Blacklist a token in Redis until it would have expired."""
        payload = decode_token(
            token, self.settings.jwt_secret, self.settings.jwt_algorithm
        )
        expires_at = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        ttl = int((expires_at - datetime.now(timezone.utc)).total_seconds())
        if ttl > 0:
            await self.redis.set(f"{BLACKLIST_PREFIX}{token}", "1", ttl)

    async def is_blacklisted(self, token: str) -> bool:
        return await self.redis.exists(f"{BLACKLIST_PREFIX}{token}")

    def _issue_token(self, user: UserModel) -> str:
        return generate_token(
            subject=str(user.id),
            secret=self.settings.jwt_secret,
            algorithm=self.settings.jwt_algorithm,
            expire_minutes=self.settings.jwt_expire_minutes,
        )
