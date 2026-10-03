import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return await self.session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        result = await self.session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def get_by_google_sub(self, google_sub: str) -> User | None:
        result = await self.session.execute(select(User).where(User.google_sub == google_sub))
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        email: str,
        hashed_password: str | None = None,
        full_name: str | None = None,
        google_sub: str | None = None,
    ) -> User:
        user = User(
            email=email,
            hashed_password=hashed_password,
            full_name=full_name,
            google_sub=google_sub,
        )
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def set_google_sub(self, user: User, google_sub: str) -> User:
        user.google_sub = google_sub
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def update_profile(
        self,
        user: User,
        *,
        full_name: str | None = None,
        phone: str | None = None,
        state: str | None = None,
        location: str | None = None,
    ) -> User:
        if full_name is not None:
            user.full_name = full_name
        if phone is not None:
            user.phone = phone
        if state is not None:
            user.state = state
        if location is not None:
            user.location = location
        await self.session.commit()
        await self.session.refresh(user)
        return user
