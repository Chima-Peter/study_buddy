from logging import Logger

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.authentication.models.user import UserDBModel, UserModel
from app.utils.errors import DuplicateEmailError, UserCreateError


class UserRepository:
    """Database access for User records.

    Holds a session factory and opens a short-lived session per operation so
    the repository is safe to share as a singleton.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession], logger: Logger):
        self.session_factory = session_factory
        self._logger = logger

    async def create(self, user: UserModel) -> UserModel:
        self._logger.debug("Creating user email=%s", user.email)
        async with self.session_factory() as session:
            db_user = UserDBModel(**user.model_dump_for_db())
            session.add(db_user)
            try:
                await session.commit()
            except IntegrityError as e:
                await session.rollback()
                if "unique" in str(e.orig).lower() or "duplicate" in str(e.orig).lower():
                    self._logger.warning("Duplicate email: %s", user.email)
                    raise DuplicateEmailError(user.email) from e
                self._logger.error("User create failed: %s", e)
                raise UserCreateError(str(e)) from e
            await session.refresh(db_user)
            self._logger.info("User created id=%s email=%s", db_user.id, db_user.email)
            return UserModel(**db_user.model_dump())

    async def get_by_email(self, email: str) -> UserModel | None:
        self._logger.debug("Get user by email=%s", email)
        async with self.session_factory() as session:
            result = await session.execute(
                select(UserDBModel).where(UserDBModel.email == email)
            )
            db_user = result.scalar_one_or_none()
            if db_user is None:
                return None
            return UserModel(**db_user.model_dump())

    async def get_by_id(self, user_id: str) -> UserModel | None:
        self._logger.debug("Get user by id=%s", user_id)
        async with self.session_factory() as session:
            db_user = await session.get(UserDBModel, user_id)
            if db_user is None:
                return None
            return UserModel(**db_user.model_dump())
