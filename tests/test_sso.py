import base64
import json
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from django.urls import reverse

from accounts import oidc
from accounts.models import SsoIdentity, User

pytestmark = pytest.mark.django_db

ISSUER = "https://sso.example.de/realms/zeit"
CLIENT_ID = "lextracker"


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def number(value: int) -> str:
    return b64(value.to_bytes((value.bit_length() + 7) // 8, "big"))


class Provider:
    """A fake OpenID Connect provider: discovery, keys and token endpoint, answered without a network."""

    def __init__(self, key=None, kid="key-1"):
        self.key = key or rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.kid = kid
        self.nonce = ""
        self.claims: dict = {}
        self.header: dict = {}
        self.token_status = 200
        self.requests: list[httpx.Request] = []

    def jwk(self) -> dict:
        public = self.key.public_key()
        if isinstance(public, rsa.RSAPublicKey):
            numbers = public.public_numbers()
            return {"kty": "RSA", "use": "sig", "kid": self.kid, "n": number(numbers.n), "e": number(numbers.e)}
        numbers = public.public_numbers()
        return {
            "kty": "EC",
            "use": "sig",
            "kid": self.kid,
            "crv": "P-256",
            "x": number(numbers.x),
            "y": number(numbers.y),
        }

    def id_token(self, **overrides) -> str:
        claims = {
            "iss": ISSUER,
            "aud": CLIENT_ID,
            "sub": "abc-123",
            "exp": int(time.time()) + 300,
            "iat": int(time.time()),
            "nonce": self.nonce,
            "email": "kim@example.de",
            "email_verified": True,
            "preferred_username": "kim",
            "given_name": "Kim",
            "family_name": "Muster",
        }
        claims = {**claims, **self.claims, **overrides}
        claims = {key: value for key, value in claims.items() if value is not None}
        ec_key = isinstance(self.key, ec.EllipticCurvePrivateKey)
        header = {"alg": "ES256" if ec_key else "RS256", "kid": self.kid} | self.header
        signed = f"{b64(json.dumps(header).encode())}.{b64(json.dumps(claims).encode())}"
        if header["alg"] == "none":
            return signed + "."
        if header["alg"].startswith("HS"):
            return signed + "." + b64(b"x" * 32)
        if ec_key:
            r, s = decode_dss_signature(self.key.sign(signed.encode(), ec.ECDSA(hashes.SHA256())))
            signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
        else:
            signature = self.key.sign(signed.encode(), padding.PKCS1v15(), hashes.SHA256())
        return signed + "." + b64(signature)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(
                200,
                json={
                    "issuer": ISSUER,
                    "authorization_endpoint": f"{ISSUER}/auth",
                    "token_endpoint": f"{ISSUER}/token",
                    "jwks_uri": f"{ISSUER}/certs",
                },
            )
        if path.endswith("/certs"):
            return httpx.Response(200, json={"keys": [self.jwk()]})
        if path.endswith("/token"):
            if self.token_status != 200:
                return httpx.Response(self.token_status, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"id_token": self.id_token(), "access_token": "x", "token_type": "Bearer"})
        return httpx.Response(404)


@pytest.fixture(autouse=True)
def clear_cache():
    oidc._cache.clear()


@pytest.fixture
def provider(monkeypatch, settings) -> Provider:
    settings.OIDC_ISSUER = ISSUER
    settings.OIDC_CLIENT_ID = CLIENT_ID
    settings.OIDC_CLIENT_SECRET = "geheim"
    settings.OIDC_NAME = "Keycloak"
    fake = Provider()
    real = httpx.AsyncClient

    def client(**kwargs):
        return real(transport=httpx.MockTransport(fake.handle), **kwargs)

    monkeypatch.setattr(oidc.httpx, "AsyncClient", client)
    return fake


@pytest.fixture
def kim(user) -> User:
    user.email = "kim@example.de"
    user.save()
    return user


def start(client, provider, **params) -> dict:
    """Begin a sign-in and return what the app sent to the provider."""
    response = client.get(reverse("accounts:sso_start"), params)
    assert response.status_code == 302
    query = parse_qs(urlsplit(response["Location"]).query)
    provider.nonce = query["nonce"][0]
    return {key: values[0] for key, values in query.items()} | {"url": response["Location"]}


def callback(client, provider, sent: dict, **overrides):
    params = {"code": "the-code", "state": sent["state"]} | overrides
    return client.get(reverse("accounts:sso_callback"), {k: v for k, v in params.items() if v is not None})


def signed_in(client) -> bool:
    return "_auth_user_id" in client.session


# The login page


def test_login_page_has_no_sso_button_without_configuration(client, user):
    page = client.get(reverse("accounts:login")).text
    assert reverse("accounts:sso_start") not in page


def test_login_page_offers_sso_next_to_the_password(client, user, provider):
    page = client.get(reverse("accounts:login")).text
    assert reverse("accounts:sso_start") in page
    assert "Mit Keycloak anmelden" in page
    assert 'name="password"' in page


def test_sso_needs_issuer_client_id_and_secret(client, user, provider, settings):
    settings.OIDC_CLIENT_SECRET = ""
    assert not oidc.enabled()
    assert client.get(reverse("accounts:sso_start")).status_code == 302
    assert not provider.requests


# Starting


def test_start_sends_the_browser_to_the_provider(client, user, provider):
    sent = start(client, provider)
    assert sent["url"].startswith(f"{ISSUER}/auth?")
    assert sent["response_type"] == "code"
    assert sent["client_id"] == CLIENT_ID
    assert sent["redirect_uri"] == "http://testserver" + reverse("accounts:sso_callback")
    assert sent["scope"] == "openid email profile"
    assert sent["code_challenge_method"] == "S256"
    assert sent["state"] and sent["nonce"] and sent["code_challenge"]


def test_start_survives_an_unreachable_provider(client, user, provider, monkeypatch):
    def broken(request):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(provider, "handle", broken)
    response = client.get(reverse("accounts:sso_start"), follow=True)
    assert response.redirect_chain[-1][0] == reverse("accounts:login")
    assert "nicht erreichbar" in response.text


def test_issuer_must_use_https(client, user, provider, settings):
    settings.OIDC_ISSUER = "http://sso.example.de"
    response = client.get(reverse("accounts:sso_start"))
    assert response["Location"] == reverse("accounts:login")
    assert not provider.requests


# Signing in


def test_existing_user_signs_in_by_verified_email(client, kim, provider):
    sent = start(client, provider)
    response = callback(client, provider, sent)
    assert response.status_code == 302
    assert response["Location"] == "/"
    assert signed_in(client)
    identity = SsoIdentity.objects.get()
    assert (identity.user, identity.issuer, identity.subject) == (kim, ISSUER, "abc-123")
    # The token request carries the code, the PKCE verifier and the client credentials.
    token_request = next(r for r in provider.requests if r.url.path.endswith("/token"))
    body = parse_qs(token_request.content.decode())
    assert body["code"] == ["the-code"] and body["grant_type"] == ["authorization_code"]
    assert body["code_verifier"][0]
    assert token_request.headers["Authorization"].startswith("Basic ")


def test_later_sign_ins_use_the_subject_not_the_email(client, kim, provider):
    SsoIdentity.objects.create(user=kim, issuer=ISSUER, subject="abc-123")
    sent = start(client, provider)
    provider.claims = {"email": "other@example.de", "email_verified": False}
    assert callback(client, provider, sent).status_code == 302
    assert signed_in(client)
    assert SsoIdentity.objects.count() == 1


def test_email_must_be_verified_by_the_provider(client, kim, provider):
    provider.claims = {"email_verified": False}
    sent = start(client, provider)
    callback(client, provider, sent)
    assert not signed_in(client)
    assert not SsoIdentity.objects.exists()


def test_email_without_verification_claim_is_not_enough(client, kim, provider):
    provider.claims = {"email_verified": None}
    sent = start(client, provider)
    callback(client, provider, sent)
    assert not signed_in(client)


def test_unknown_person_gets_no_account_by_default(client, kim, provider):
    provider.claims = {"email": "neu@example.de", "sub": "neu"}
    sent = start(client, provider)
    response = callback(client, provider, sent, follow=None)
    assert response["Location"] == reverse("accounts:login")
    assert not signed_in(client)
    assert User.objects.count() == 1
    page = client.get(reverse("accounts:login")).text
    assert "keinen Benutzer" in page


def test_unknown_person_gets_an_employee_when_allowed(client, kim, provider, settings):
    settings.OIDC_CREATE_USERS = True
    provider.claims = {"email": "neu@example.de", "sub": "neu", "preferred_username": "neu"}
    sent = start(client, provider)
    callback(client, provider, sent)
    assert signed_in(client)
    created = User.objects.get(email="neu@example.de")
    assert created.username == "neu"
    assert created.role == User.Role.EMPLOYEE
    assert not created.is_staff and not created.is_superuser
    assert not created.has_usable_password()
    assert (created.first_name, created.last_name) == ("Kim", "Muster")
    assert SsoIdentity.objects.get(user=created).subject == "neu"


def test_created_user_gets_a_free_username(client, kim, provider, settings):
    settings.OIDC_CREATE_USERS = True
    provider.claims = {"email": "neu@example.de", "sub": "neu", "preferred_username": "Kim"}
    sent = start(client, provider)
    callback(client, provider, sent)
    assert User.objects.get(email="neu@example.de").username == "Kim2"


def test_created_users_can_be_limited_to_email_domains(client, kim, provider, settings):
    settings.OIDC_CREATE_USERS = True
    settings.OIDC_ALLOWED_EMAIL_DOMAINS = ["example.de"]
    provider.claims = {"email": "x@fremd.example", "sub": "x"}
    callback(client, provider, start(client, provider))
    assert not signed_in(client)
    provider.claims = {"email": "ok@example.de", "sub": "ok"}
    callback(client, provider, start(client, provider))
    assert signed_in(client)


def test_deactivated_user_cannot_sign_in(client, kim, provider):
    kim.is_active = False
    kim.save()
    callback(client, provider, start(client, provider))
    assert not signed_in(client)
    assert not SsoIdentity.objects.exists()


def test_deactivated_user_with_a_link_cannot_sign_in(client, kim, provider):
    SsoIdentity.objects.create(user=kim, issuer=ISSUER, subject="abc-123")
    kim.is_active = False
    kim.save()
    callback(client, provider, start(client, provider))
    assert not signed_in(client)


def test_ambiguous_email_signs_nobody_in(client, kim, provider):
    User.objects.create_user(username="mia", password="x", email="KIM@example.de")
    callback(client, provider, start(client, provider))
    assert not signed_in(client)


def test_sign_in_goes_on_to_the_requested_page(client, kim, provider):
    sent = start(client, provider, next="/customers/")
    assert callback(client, provider, sent)["Location"] == "/customers/"


def test_sign_in_does_not_leave_the_site(client, kim, provider):
    sent = start(client, provider, next="https://evil.example/")
    assert callback(client, provider, sent)["Location"] == "/"


def test_local_login_keeps_working(client, kim, provider):
    response = client.post(reverse("accounts:login"), {"username": "kim", "password": "geheim-123"})
    assert response.status_code == 302
    assert signed_in(client)


# What the callback refuses


def test_wrong_state_is_refused(client, kim, provider):
    sent = start(client, provider)
    callback(client, provider, sent, state="other")
    assert not signed_in(client)
    assert not any(r.url.path.endswith("/token") for r in provider.requests)


def test_callback_without_a_started_sign_in_is_refused(client, kim, provider):
    client.get(reverse("accounts:sso_callback"), {"code": "c", "state": "s"})
    assert not signed_in(client)


def test_an_attempt_can_only_be_finished_once(client, kim, provider):
    sent = start(client, provider)
    callback(client, provider, sent)
    client.post(reverse("accounts:logout"))
    callback(client, provider, sent)
    assert not signed_in(client)


def test_provider_error_is_refused(client, kim, provider):
    sent = start(client, provider)
    response = callback(client, provider, sent, code=None, error="access_denied")
    assert response["Location"] == reverse("accounts:login")
    assert not signed_in(client)


def test_refused_code_is_refused(client, kim, provider):
    sent = start(client, provider)
    provider.token_status = 400
    callback(client, provider, sent)
    assert not signed_in(client)


@pytest.mark.parametrize(
    "claims",
    [
        {"iss": "https://evil.example"},
        {"aud": "someone-else"},
        {"aud": [CLIENT_ID, "other"]},
        {"exp": 1},
        {"nonce": "other"},
        {"nonce": None},
        {"sub": None},
    ],
)
def test_bad_id_token_claims_are_refused(client, kim, provider, claims):
    provider.claims = claims
    callback(client, provider, start(client, provider))
    assert not signed_in(client)


def test_audience_list_with_matching_azp_is_fine(client, kim, provider):
    provider.claims = {"aud": [CLIENT_ID, "other"], "azp": CLIENT_ID}
    callback(client, provider, start(client, provider))
    assert signed_in(client)


@pytest.mark.parametrize("alg", ["none", "HS256"])
def test_unsigned_or_symmetric_tokens_are_refused(client, kim, provider, alg):
    provider.header = {"alg": alg}
    callback(client, provider, start(client, provider))
    assert not signed_in(client)


def test_token_signed_with_another_key_is_refused(client, kim, provider):
    other = Provider()
    sent = start(client, provider)
    provider.token_status = 200
    original = provider.id_token
    provider.id_token = lambda **kw: Provider.id_token(other, **kw)
    callback(client, provider, sent)
    provider.id_token = original
    assert not signed_in(client)


def test_token_with_an_unknown_key_id_is_refused(client, kim, provider):
    provider.header = {"kid": "unknown"}
    callback(client, provider, start(client, provider))
    assert not signed_in(client)


def test_elliptic_curve_keys_work(client, kim, provider):
    provider.key = ec.generate_private_key(ec.SECP256R1())
    callback(client, provider, start(client, provider))
    assert signed_in(client)


def test_new_signing_keys_are_picked_up(client, kim, provider):
    start_sent = start(client, provider)
    # The provider rotates its key after the app has cached the old key set.
    oidc._cache.clear()
    callback(client, provider, start_sent)
    assert signed_in(client)
    client.post(reverse("accounts:logout"))
    provider.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    provider.kid = "key-2"
    callback(client, provider, start(client, provider))
    assert signed_in(client)


def test_failed_sign_ins_count_towards_the_rate_limit(client, kim, provider):
    from core.models import AppSettings

    settings_row = AppSettings.load()
    settings_row.login_max_attempts = 2
    settings_row.save()
    for _ in range(2):
        callback(client, provider, start(client, provider), state="wrong")
    response = client.get(reverse("accounts:sso_callback"), {"code": "c", "state": "s"})
    assert response.status_code == 429
