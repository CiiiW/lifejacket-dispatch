"""Firebase/Identity Platform token verification; never trusts role claims."""

import os
from dataclasses import dataclass
from functools import lru_cache


class InvalidIdentity(Exception):
    pass


class IdentityUnavailable(Exception):
    pass


@dataclass(frozen=True)
class VerifiedIdentity:
    issuer: str
    subject: str
    email: str | None = None
    email_verified: bool = False


@lru_cache(maxsize=4)
def _firebase_app(project_id):
    import firebase_admin

    # ADC on GCP; do not create or export service-account keys.
    name = "lifejacket-auth-" + project_id
    try:
        return firebase_admin.get_app(name)
    except ValueError:
        return firebase_admin.initialize_app(
            options={"projectId": project_id, "httpTimeout": 10}, name=name
        )


def verify_provider_token(token: str, project_id: str) -> VerifiedIdentity:
    """SDK verifies signature, issuer/audience/expiry and provider revocation.

    App memberships are loaded afresh from our DB, not Firebase custom claims.
    Emulator tokens are never accepted through this adapter.
    """
    if not project_id or os.environ.get("FIREBASE_AUTH_EMULATOR_HOST"):
        raise IdentityUnavailable("Managed identity verification is not configured")
    try:
        from firebase_admin import auth
    except ImportError as exc:
        raise IdentityUnavailable("Managed identity dependency unavailable") from exc
    try:
        claims = auth.verify_id_token(token, app=_firebase_app(project_id), check_revoked=True)
    except (
        auth.InvalidIdTokenError,
        auth.ExpiredIdTokenError,
        auth.RevokedIdTokenError,
        auth.UserDisabledError,
        ValueError,
    ) as exc:
        raise InvalidIdentity("Invalid sign-in token") from exc
    except Exception as exc:
        # Includes ADC/IAM, certificate-fetch and provider availability failures.
        # Do not leak provider errors or credentials into a public response/log.
        raise IdentityUnavailable("Identity verification is temporarily unavailable") from exc
    expected_issuer = "https://securetoken.google.com/" + project_id
    subject = claims.get("sub")
    if (
        claims.get("iss") != expected_issuer
        or claims.get("aud") != project_id
        or not isinstance(subject, str)
        or not 1 <= len(subject) <= 128
        or subject != subject.strip()
        or "/" in subject
    ):
        raise InvalidIdentity("Invalid provider identity")
    email = claims.get("email")
    return VerifiedIdentity(
        expected_issuer,
        subject,
        email if isinstance(email, str) else None,
        claims.get("email_verified") is True
        and isinstance(email, str)
        and bool(email.strip()),
    )
