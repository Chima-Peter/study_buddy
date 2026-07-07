import uuid
from datetime import datetime, timezone

from app.authentication.models.user import User
from app.authentication.repository.user_repository import UserRepository
from app.config import Settings
from app.core.redis import RedisClient
from app.utils.errors import DuplicateEmailError, EmailAlreadyExistsError, UserNotFoundError
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

    async def register(self, name: str, email: str) -> User:
        try:
            return await self.repository.create(name=name, email=email)
        except DuplicateEmailError as e:
            raise EmailAlreadyExistsError(email) from e

    async def login(self, email: str) -> str:
        user = await self.repository.get_by_email(email)
        if user is None:
            raise UserNotFoundError(email)
        return self._issue_token(user)

    async def get_user(self, user_id: uuid.UUID) -> User | None:
        return await self.repository.get_by_id(user_id)

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

    def _issue_token(self, user: User) -> str:
        return generate_token(
            subject=str(user.id),
            secret=self.settings.jwt_secret,
            algorithm=self.settings.jwt_algorithm,
            expire_minutes=self.settings.jwt_expire_minutes,
        )
