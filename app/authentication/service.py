from datetime import datetime, timezone
from logging import Logger

from app.system.notification.schema import EventPayload
import jwt

from app.authentication.schema import (
    BLACKLIST_PREFIX,
    LoginRequest,
    LoginResponse,
    RegisterRequest,
)
from app.config import Settings
from app.core.rabbitmq import RabbitMQ
from app.core.redis import RedisClient
from app.mail.schema import AuthEmailRequest
from app.system.user.model import UserModel
from app.system.user.repository import UserRepository
from app.system.user.schema import UserResponse
from app.utils.bcrypt import hash_password, verify_password
from app.utils.errors import DuplicateEmailError, EmailAlreadyExistsError, UserNotFoundError
from app.utils.errors.auth import InvalidCredentialsError
from app.utils.jwt import generate_token


class AuthService:
    """Authentication business logic."""

    def __init__(
        self,
        repository: UserRepository,
        redis: RedisClient,
        settings: Settings,
        rabbitmq: RabbitMQ,
        logger: Logger,
    ):
        self.repository = repository
        self.redis = redis
        self.settings = settings
        self.rabbitmq = rabbitmq
        self._logger = logger

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
            await self._enqueue_signup_email(user)
            self._logger.info("Register success user_id=%s email=%s", user.id, user.email)
            return LoginResponse(
                user=self._to_response(user),
                token=token,
            )
        except DuplicateEmailError as e:
            self._logger.warning("Register failed - email exists: %s", request.email)
            raise EmailAlreadyExistsError(request.email) from e

    async def _enqueue_signup_email(self, user: UserModel) -> None:
        try:
            payload = AuthEmailRequest(
                type="signup",
                to=user.email,
                name=user.name,
                user_id=str(user.id),
            )
            await self.rabbitmq.publish_message(
                "auth_email_queue",
                payload.model_dump(mode="json"),
            )
        except Exception:
            self._logger.exception(
                "Failed to enqueue signup email user_id=%s email=%s",
                user.id,
                user.email,
            )
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
        
        await self.redis.set(f"auth_{user.id}", user.id, ttl=self.settings.jwt_expire_minutes * 60)

        self._logger.info("Login success user_id=%s email=%s", user.id, user.email)
        return LoginResponse(
            user=self._to_response(user),
            token=token,
        )

    async def refresh_token(self, token: str) -> LoginResponse:
        self._logger.info("Refresh token attempt")
        if await self.is_blacklisted(token):
            self._logger.warning("Refresh token failed - blacklisted token")
            raise InvalidCredentialsError("Token blacklisted")

        try:
            payload = jwt.decode(
                token,
                self.settings.jwt_secret,
                algorithms=[self.settings.jwt_algorithm],
                options={"verify_exp": False},
            )
        except jwt.InvalidTokenError:
            self._logger.warning("Refresh token failed - invalid token")
            raise InvalidCredentialsError("Invalid token")

        exp = payload.get("exp")
        if exp is None:
            self._logger.warning("Refresh token failed - missing expiry")
            raise InvalidCredentialsError("Invalid token")

        now = datetime.now(timezone.utc)
        expires_at = datetime.fromtimestamp(exp, tz=timezone.utc)
        seconds_since_expiry = (now - expires_at).total_seconds()
        grace_seconds = self.settings.jwt_refresh_grace_minutes * 60

        if seconds_since_expiry < 0:
            self._logger.warning("Refresh token failed - token not expired")
            raise InvalidCredentialsError("Invalid token")
        if seconds_since_expiry > grace_seconds:
            self._logger.warning("Refresh token failed - refresh window expired")
            raise InvalidCredentialsError("Invalid token")

        user_id = payload.get("sub")
        if not user_id:
            self._logger.warning("Refresh token failed - missing subject")
            raise InvalidCredentialsError("Invalid token")

        user = await self.repository.get_by_id(user_id)
        if user is None:
            self._logger.warning("Refresh token failed - user not found: %s", user_id)
            raise UserNotFoundError(user_id)

        await self._blacklist_token(token, payload)

        new_token = self._issue_token(user)

        await self.redis.set(
            f"auth_{user_id}",
            user.id,
            ttl=self.settings.jwt_expire_minutes * 60,
        )

        self._logger.info("Refresh token success user_id=%s", user.id)
        return LoginResponse(
            user=self._to_response(user),
            token=new_token,
        )

    async def logout(self, token: str) -> None:
        """Blacklist a still-valid token for its remaining lifetime."""
        try:
            payload = jwt.decode(
                token,
                self.settings.jwt_secret,
                algorithms=[self.settings.jwt_algorithm],
            )
        except jwt.ExpiredSignatureError:
            self._logger.warning("Logout failed - token expired")
            raise InvalidCredentialsError("token")
        except jwt.InvalidTokenError:
            self._logger.warning("Logout failed - invalid token")
            raise InvalidCredentialsError("token")

        if await self.is_blacklisted(token):
            self._logger.warning("Logout failed - token already blacklisted")
            raise InvalidCredentialsError("token")

        user_id = payload.get("sub")
        exp = payload.get("exp")
        if exp is None:
            raise InvalidCredentialsError("token")

        now = datetime.now(timezone.utc)
        expires_at = datetime.fromtimestamp(exp, tz=timezone.utc)
        remaining = max(0, int((expires_at - now).total_seconds()))

        ttl = remaining + self.settings.jwt_refresh_grace_minutes * 60
        if ttl > 0:
            await self.redis.set(f"{BLACKLIST_PREFIX}{token}", "1", ttl)

        await self._close_connections(user_id)

        self._logger.info("Logout success user_id=%s", user_id)

    async def _blacklist_token(self, token: str, payload: dict) -> None:
        """Blacklist an expired token for the leftover refresh grace window."""
        exp = payload.get("exp")
        if exp is None:
            return

        now = datetime.now(timezone.utc)
        expires_at = datetime.fromtimestamp(exp, tz=timezone.utc)
        seconds_since_expiry = int((now - expires_at).total_seconds())
        ttl = max(
            0,
            self.settings.jwt_refresh_grace_minutes * 60 - seconds_since_expiry,
        )
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
            claims={
                "name": user.name,
                "email": user.email,
                "gender": user.gender,
                "university": user.university,
                "bio": user.bio,
                "timezone": user.timezone,
                "created_at": user.created_at.isoformat(),
                "updated_at": user.updated_at.isoformat(),
            },
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

    async def _close_connections(self, user_id: str) -> None:
        await self.redis.delete(f"auth_{user_id}")
        await self.redis.publish_to_user(
            user_id,
            EventPayload(
                type="auth.logout",
                data={
                    "user_id": user_id,
                    "message": "User has logged out",
                },
            ),
        )
