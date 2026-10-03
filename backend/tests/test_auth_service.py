import pytest

from app.core.security import decode_token
from app.integrations.google_auth import GoogleProfile
from app.services.auth_service import INVALID_CREDENTIALS_MESSAGE, AuthError, AuthService

EMAIL = "farmer@example.com"
PASSWORD = "correct-horse-battery-staple"
GOOGLE_SUB = "google-sub-123"


def _google_profile(*, email: str = EMAIL, email_verified: bool = True, sub: str = GOOGLE_SUB) -> GoogleProfile:
    return GoogleProfile(sub=sub, email=email, email_verified=email_verified, full_name="Farmer Jo")


async def _register(auth_service: AuthService, *, email: str = EMAIL, password: str = PASSWORD):
    return await auth_service.register(email=email, password=password, full_name="Farmer Jo")


class TestRegister:
    async def test_creates_user_with_hashed_password(self, auth_service: AuthService) -> None:
        user = await _register(auth_service)

        assert user.email == EMAIL
        assert user.hashed_password != PASSWORD
        assert user.is_active is True

    async def test_rejects_duplicate_email(self, auth_service: AuthService) -> None:
        await _register(auth_service)

        with pytest.raises(AuthError):
            await _register(auth_service)


class TestLogin:
    async def test_returns_valid_access_and_refresh_tokens(
        self, auth_service: AuthService
    ) -> None:
        user = await _register(auth_service)

        access_token, refresh_token = await auth_service.login(email=EMAIL, password=PASSWORD)

        access_payload = decode_token(access_token)
        refresh_payload = decode_token(refresh_token)
        assert access_payload["sub"] == str(user.id)
        assert access_payload["type"] == "access"
        assert refresh_payload["sub"] == str(user.id)
        assert refresh_payload["type"] == "refresh"

    async def test_unknown_email_and_wrong_password_raise_identical_message(
        self, auth_service: AuthService
    ) -> None:
        await _register(auth_service)

        with pytest.raises(AuthError) as unknown_user_exc:
            await auth_service.login(email="nobody@example.com", password=PASSWORD)

        with pytest.raises(AuthError) as wrong_password_exc:
            await auth_service.login(email=EMAIL, password="not-the-password")

        assert str(unknown_user_exc.value) == INVALID_CREDENTIALS_MESSAGE
        assert str(wrong_password_exc.value) == INVALID_CREDENTIALS_MESSAGE
        assert str(unknown_user_exc.value) == str(wrong_password_exc.value)

    async def test_inactive_user_cannot_login(self, auth_service: AuthService) -> None:
        user = await _register(auth_service)
        user.is_active = False
        await auth_service.user_repository.session.commit()

        with pytest.raises(AuthError) as exc:
            await auth_service.login(email=EMAIL, password=PASSWORD)

        assert str(exc.value) == INVALID_CREDENTIALS_MESSAGE


class TestLoginWithGoogle:
    async def test_creates_new_user_on_first_google_login(
        self, auth_service: AuthService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "app.services.auth_service.verify_google_id_token", lambda token: _google_profile()
        )

        access_token, _ = await auth_service.login_with_google("fake-id-token")

        user = await auth_service.user_repository.get_by_email(EMAIL)
        assert user is not None
        assert user.google_sub == GOOGLE_SUB
        assert user.hashed_password is None
        assert decode_token(access_token)["sub"] == str(user.id)

    async def test_links_google_sub_to_existing_password_user(
        self, auth_service: AuthService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        existing = await _register(auth_service)
        monkeypatch.setattr(
            "app.services.auth_service.verify_google_id_token", lambda token: _google_profile()
        )

        access_token, _ = await auth_service.login_with_google("fake-id-token")

        assert decode_token(access_token)["sub"] == str(existing.id)
        linked = await auth_service.user_repository.get_by_google_sub(GOOGLE_SUB)
        assert linked is not None
        assert linked.id == existing.id

    async def test_reuses_existing_google_user_on_repeat_login(
        self, auth_service: AuthService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "app.services.auth_service.verify_google_id_token", lambda token: _google_profile()
        )

        await auth_service.login_with_google("fake-id-token")
        access_token, _ = await auth_service.login_with_google("fake-id-token")

        user = await auth_service.user_repository.get_by_email(EMAIL)
        assert decode_token(access_token)["sub"] == str(user.id)

    async def test_rejects_unverified_email(
        self, auth_service: AuthService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "app.services.auth_service.verify_google_id_token",
            lambda token: _google_profile(email_verified=False),
        )

        with pytest.raises(AuthError):
            await auth_service.login_with_google("fake-id-token")

    async def test_rejects_invalid_token(
        self, auth_service: AuthService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.integrations.google_auth import GoogleTokenError

        def _raise(token: str) -> GoogleProfile:
            raise GoogleTokenError("Invalid Google sign-in token.")

        monkeypatch.setattr("app.services.auth_service.verify_google_id_token", _raise)

        with pytest.raises(AuthError):
            await auth_service.login_with_google("garbage")


class TestRefreshToken:
    async def test_issues_new_access_token_for_valid_refresh_token(
        self, auth_service: AuthService
    ) -> None:
        user = await _register(auth_service)
        _, refresh_token = await auth_service.login(email=EMAIL, password=PASSWORD)

        new_access_token = await auth_service.refresh_token(refresh_token)

        payload = decode_token(new_access_token)
        assert payload["sub"] == str(user.id)
        assert payload["type"] == "access"

    async def test_rejects_malformed_token(self, auth_service: AuthService) -> None:
        with pytest.raises(AuthError):
            await auth_service.refresh_token("not-a-real-token")

    async def test_rejects_access_token_used_as_refresh_token(
        self, auth_service: AuthService
    ) -> None:
        await _register(auth_service)
        access_token, _ = await auth_service.login(email=EMAIL, password=PASSWORD)

        with pytest.raises(AuthError):
            await auth_service.refresh_token(access_token)

    async def test_rejects_token_for_deleted_or_deactivated_user(
        self, auth_service: AuthService
    ) -> None:
        user = await _register(auth_service)
        _, refresh_token = await auth_service.login(email=EMAIL, password=PASSWORD)
        user.is_active = False
        await auth_service.user_repository.session.commit()

        with pytest.raises(AuthError):
            await auth_service.refresh_token(refresh_token)
