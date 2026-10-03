"""Verifies "Sign in with Google" ID tokens issued to the frontend."""

from dataclasses import dataclass

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

from app.core.config import settings

_google_request = google_requests.Request()


@dataclass(frozen=True)
class GoogleProfile:
    sub: str
    email: str
    email_verified: bool
    full_name: str | None


class GoogleTokenError(Exception):
    """Raised when a Google ID token is missing, malformed, or fails verification."""


def verify_google_id_token(token: str) -> GoogleProfile:
    if not settings.GOOGLE_CLIENT_ID:
        raise GoogleTokenError("Google sign-in is not configured on this server.")

    try:
        claims = google_id_token.verify_oauth2_token(
            token, _google_request, audience=settings.GOOGLE_CLIENT_ID
        )
    except ValueError as exc:
        raise GoogleTokenError("Invalid Google sign-in token.") from exc

    return GoogleProfile(
        sub=claims["sub"],
        email=claims["email"],
        email_verified=claims.get("email_verified", False),
        full_name=claims.get("name"),
    )
