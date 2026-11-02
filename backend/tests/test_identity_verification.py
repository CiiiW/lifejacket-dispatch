import pytest
from firebase_admin import auth
from lifejacket.access import identity


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.delenv("FIREBASE_AUTH_EMULATOR_HOST", raising=False)
    app = object()
    monkeypatch.setattr(identity, "_firebase_app", lambda project: app)
    claims = {
        "iss": "https://securetoken.google.com/test-project",
        "aud": "test-project",
        "sub": "person",
        "email": "person@example.org",
        "email_verified": True,
        "role": "noaa",
        "states": ["AK"],
    }
    calls = []

    def verify(token, **kwargs):
        calls.append((token, kwargs))
        return claims

    monkeypatch.setattr(auth, "verify_id_token", verify)
    return claims, calls, app


def test_sdk_checks_revocation_and_does_not_supply_app_roles(provider):
    claims, calls, app = provider
    person = identity.verify_provider_token("signed-token", "test-project")
    assert calls == [("signed-token", {"app": app, "check_revoked": True})]
    assert person.subject == "person" and person.email_verified
    assert not hasattr(person, "role")


@pytest.mark.parametrize(
    "field,value",
    [
        ("iss", "other"),
        ("aud", "other"),
        ("sub", ""),
        ("sub", "x" * 129),
        ("sub", " person"),
        ("sub", "a/b"),
        ("sub", None),
    ],
)
def test_wrong_provider_or_subject_rejected(provider, field, value):
    provider[0][field] = value
    with pytest.raises(identity.InvalidIdentity):
        identity.verify_provider_token("token", "test-project")


@pytest.mark.parametrize(
    "error",
    [
        auth.InvalidIdTokenError,
        auth.ExpiredIdTokenError,
        auth.RevokedIdTokenError,
        auth.UserDisabledError,
    ],
)
def test_provider_rejection_is_not_an_authenticated_session(provider, monkeypatch, error):
    def reject(*args, **kwargs):
        raise (
            error("private diagnostic", cause=None)
            if error is auth.ExpiredIdTokenError
            else error("private diagnostic")
        )

    monkeypatch.setattr(auth, "verify_id_token", reject)
    with pytest.raises(identity.InvalidIdentity):
        identity.verify_provider_token("token", "test-project")


def test_provider_outage_and_emulator_fail_closed(provider, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("private diagnostic")

    monkeypatch.setattr(auth, "verify_id_token", fail)
    with pytest.raises(identity.IdentityUnavailable):
        identity.verify_provider_token("token", "test-project")
    monkeypatch.setenv("FIREBASE_AUTH_EMULATOR_HOST", "localhost:9099")
    with pytest.raises(identity.IdentityUnavailable):
        identity.verify_provider_token("token", "test-project")
    assert provider[1] == []


@pytest.mark.parametrize(
    "email,verified", [(None, True), ("", True), ("x@y.z", "true"), ("x@y.z", False)]
)
def test_email_verification_is_explicit(provider, email, verified):
    provider[0].update(email=email, email_verified=verified)
    assert not identity.verify_provider_token("token", "test-project").email_verified
