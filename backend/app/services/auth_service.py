import uuid

import jwt

from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.integrations.google_auth import GoogleTokenError, verify_google_id_token
from app.models.user import User
from app.repositories.user_repository import UserRepository

# Deliberately identical for "no such user" and "wrong password" so a login
# failure never reveals whether the email is registered.
INVALID_CREDENTIALS_MESSAGE = "Invalid email or password."


class AuthError(Exception):
    """Raised for any auth failure. The message is safe to return to the client."""


class AuthService:
    def __init__(self, user_repository: UserRepository) -> None:
        self.user_repository = user_repository

    async def register(
        self,
        *,
        email: str,
        password: str,
        full_name: str | None = None,
        phone: str | None = None,
        state: str | None = None,
        location: str | None = None,
    ) -> User:
        if await self.user_repository.get_by_email(email) is not None:
            raise AuthError("A user with this email already exists.")
        user = await self.user_repository.create(
            email=email, hashed_password=hash_password(password), full_name=full_name
        )
        if phone or state or location:
            user = await self.user_repository.update_profile(
                user, phone=phone, state=state, location=location
            )
        return user

    async def login(self, *, email: str, password: str) -> tuple[str, str]:
        user = await self.user_repository.get_by_email(email)
        if user is None or not verify_password(password, user.hashed_password):
            raise AuthError(INVALID_CREDENTIALS_MESSAGE)
        if not user.is_active:
            raise AuthError(INVALID_CREDENTIALS_MESSAGE)

        subject = str(user.id)
        return create_access_token(subject), create_refresh_token(subject)

    async def login_with_google(self, id_token: str) -> tuple[str, str]:
        try:
            profile = verify_google_id_token(id_token)
        except GoogleTokenError as exc:
            raise AuthError(str(exc)) from exc

        if not profile.email_verified:
            raise AuthError("Google account email is not verified.")

        user = await self.user_repository.get_by_google_sub(profile.sub)
        if user is None:
            user = await self.user_repository.get_by_email(profile.email)
            if user is None:
                user = await self.user_repository.create(
                    email=profile.email,
                    full_name=profile.full_name,
                    google_sub=profile.sub,
                )
            elif user.google_sub is None:
                user = await self.user_repository.set_google_sub(user, profile.sub)

        if not user.is_active:
            raise AuthError(INVALID_CREDENTIALS_MESSAGE)

        subject = str(user.id)
        return create_access_token(subject), create_refresh_token(subject)

    async def refresh_token(self, refresh_token: str) -> str:
        try:
            payload = decode_token(refresh_token)
        except jwt.PyJWTError as exc:
            raise AuthError("Invalid or expired refresh token.") from exc

        if payload.get("type") != "refresh":
            raise AuthError("Invalid or expired refresh token.")

        user = await self.user_repository.get_by_id(uuid.UUID(payload["sub"]))
        if user is None or not user.is_active:
            raise AuthError("Invalid or expired refresh token.")

        return create_access_token(str(user.id))

    async def update_profile(
        self,
        user: User,
        *,
        full_name: str | None = None,
        phone: str | None = None,
        state: str | None = None,
        location: str | None = None,
    ) -> User:
        return await self.user_repository.update_profile(
            user, full_name=full_name, phone=phone, state=state, location=location
        )
