from logging import Logger

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.authentication.models.user import UserDBModel, UserModel
from app.system.models.chat import ChatDBModel
from app.system.models.conversation import ConversationDBModel
from app.system.models.documents import DocumentDBModel
from app.system.models.notifications import NotificationDBModel
from app.utils.errors.user import DuplicateEmailError, UserCreateError


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

    async def update(self, user: UserModel) -> UserModel:
        self._logger.debug("Updating user id=%s", user.id)
        async with self.session_factory() as session:
            db_user = await session.get(UserDBModel, user.id)
            if db_user is None:
                raise ValueError(f"User not found: {user.id}")

            db_user.name = user.name
            db_user.email = user.email
            db_user.hashed_password = user.hashed_password
            db_user.gender = user.gender
            db_user.university = user.university
            db_user.bio = user.bio
            db_user.timezone = user.timezone
            db_user.updated_at = user.updated_at

            try:
                await session.commit()
            except IntegrityError as e:
                await session.rollback()
                if "unique" in str(e.orig).lower() or "duplicate" in str(e.orig).lower():
                    self._logger.warning("Duplicate email on update: %s", user.email)
                    raise DuplicateEmailError(user.email) from e
                self._logger.error("User update failed: %s", e)
                raise UserCreateError(str(e)) from e

            await session.refresh(db_user)
            self._logger.info("User updated id=%s", db_user.id)
            return UserModel(**db_user.model_dump())

    async def list_document_paths(self, user_id: str) -> list[str]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(DocumentDBModel.path).where(
                    DocumentDBModel.user_id == user_id,
                    DocumentDBModel.path.is_not(None),
                )
            )
            return [path for path in result.scalars().all() if path]

    async def delete(self, user_id: str) -> bool:
        self._logger.debug("Deleting user id=%s", user_id)
        async with self.session_factory() as session:
            db_user = await session.get(UserDBModel, user_id)
            if db_user is None:
                return False

            conversation_ids = (
                await session.execute(
                    select(ConversationDBModel.id).where(
                        ConversationDBModel.user_id == user_id
                    )
                )
            ).scalars().all()

            if conversation_ids:
                await session.execute(
                    delete(ChatDBModel).where(
                        ChatDBModel.conversation_id.in_(conversation_ids)
                    )
                )
            await session.execute(
                delete(ConversationDBModel).where(
                    ConversationDBModel.user_id == user_id
                )
            )
            await session.execute(
                delete(DocumentDBModel).where(DocumentDBModel.user_id == user_id)
            )
            await session.execute(
                delete(NotificationDBModel).where(
                    NotificationDBModel.user_id == user_id
                )
            )
            await session.delete(db_user)

            try:
                await session.commit()
            except IntegrityError as e:
                await session.rollback()
                self._logger.error("User delete failed id=%s: %s", user_id, e)
                raise UserCreateError(str(e)) from e

            self._logger.info("User deleted id=%s", user_id)
            return True
