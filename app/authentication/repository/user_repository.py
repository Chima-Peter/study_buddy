import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.authentication.models.user import User
from app.utils.errors import DuplicateEmailError, UserCreateError


class UserRepository:
    """Database access for User records.

    Holds a session factory and opens a short-lived session per operation so
    the repository is safe to share as a singleton.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    async def create(self, name: str, email: str) -> User:
        async with self.session_factory() as session:
            user = User(name=name, email=email)
            session.add(user)
            try:
                await session.commit()
            except IntegrityError as e:
                await session.rollback()
                if "unique" in str(e.orig).lower() or "duplicate" in str(e.orig).lower():
                    raise DuplicateEmailError(email) from e
                raise UserCreateError(str(e)) from e
            await session.refresh(user)
            return user

    async def get_by_email(self, email: str) -> User | None:
        async with self.session_factory() as session:
            result = await session.execute(
                select(User).where(User.email == email)
            )
            return result.scalar_one_or_none()

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        async with self.session_factory() as session:
            return await session.get(User, user_id)
