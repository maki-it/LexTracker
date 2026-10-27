"""Single sign-on with OpenID Connect (authorization code flow with PKCE).

Configured with ``APP_OIDC_ISSUER``, ``APP_OIDC_CLIENT_ID`` and ``APP_OIDC_CLIENT_SECRET``. The login with
username and password stays. The provider's endpoints come from its discovery document, the ID token is
checked against the provider's keys (RS*/ES* signatures only), and a user is found by the provider's
``sub`` or, the first time, by an e-mail address the provider has verified.
"""

import base64
import hashlib
import json
import secrets
import time
from contextlib import suppress
from dataclasses import dataclass
from urllib.parse import quote_plus, urlsplit

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from django.conf import settings
from django.db import IntegrityError

from accounts.models import SsoIdentity, User

TIMEOUT = 10
CACHE_SECONDS = 3600
# Seconds the clocks of the provider and this server may differ.
LEEWAY = 60

_HASHES = {"256": hashes.SHA256, "384": hashes.SHA384, "512": hashes.SHA512}
_CURVES = {"P-256": ec.SECP256R1, "P-384": ec.SECP384R1, "P-521": ec.SECP521R1}

_cache: dict[str, tuple[float, dict]] = {}


class SsoError(Exception):
    """The sign-in cannot continue. The message is for the log, the user sees a general one."""


class NoAccount(SsoError):
    """The provider vouches for the person, but no account here belongs to them (and none may be created)."""


def enabled() -> bool:
    return bool(settings.OIDC_ISSUER and settings.OIDC_CLIENT_ID and settings.OIDC_CLIENT_SECRET)


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def new_login() -> dict:
    """The secrets of one sign-in attempt: ``state`` ties the callback to the browser, ``nonce`` the ID token to
    this attempt, and the PKCE ``verifier`` the code to whoever asked for it."""
    return {
        "state": secrets.token_urlsafe(32),
        "nonce": secrets.token_urlsafe(32),
        "verifier": secrets.token_urlsafe(64),
    }


def _challenge(verifier: str) -> str:
    return _b64encode(hashlib.sha256(verifier.encode()).digest())


async def _get_json(url: str, *, ttl: bool = True, force: bool = False) -> dict:
    cached = _cache.get(url)
    if ttl and not force and cached and time.monotonic() - cached[0] < CACHE_SECONDS:
        return cached[1]
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise SsoError(f"Could not load {url}: {error}") from error
    if not isinstance(data, dict):
        raise SsoError(f"{url} did not return a JSON object")
    _cache[url] = (time.monotonic(), data)
    return data


async def discovery() -> dict:
    issuer = settings.OIDC_ISSUER
    parts = urlsplit(issuer)
    if parts.scheme != "https" and not (parts.scheme == "http" and parts.hostname in ("localhost", "127.0.0.1")):
        raise SsoError("APP_OIDC_ISSUER must be an https address")
    document = await _get_json(f"{issuer.rstrip('/')}/.well-known/openid-configuration")
    if str(document.get("issuer", "")).rstrip("/") != issuer.rstrip("/"):
        raise SsoError("The issuer in the discovery document is not the configured one")
    for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        if not document.get(key):
            raise SsoError(f"The discovery document has no {key}")
    return document


async def authorization_url(redirect_uri: str, login: dict) -> str:
    document = await discovery()
    query = httpx.QueryParams(
        {
            "response_type": "code",
            "client_id": settings.OIDC_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "scope": settings.OIDC_SCOPES,
            "state": login["state"],
            "nonce": login["nonce"],
            "code_challenge": _challenge(login["verifier"]),
            "code_challenge_method": "S256",
        }
    )
    separator = "&" if "?" in document["authorization_endpoint"] else "?"
    return f"{document['authorization_endpoint']}{separator}{query}"


def _public_key(jwk: dict):
    try:
        if jwk["kty"] == "RSA":
            numbers = rsa.RSAPublicNumbers(int.from_bytes(_b64decode(jwk["e"])), int.from_bytes(_b64decode(jwk["n"])))
            return numbers.public_key()
        if jwk["kty"] == "EC":
            numbers = ec.EllipticCurvePublicNumbers(
                int.from_bytes(_b64decode(jwk["x"])), int.from_bytes(_b64decode(jwk["y"])), _CURVES[jwk["crv"]]()
            )
            return numbers.public_key()
    except (KeyError, ValueError) as error:
        raise SsoError(f"Unusable key in the provider's key set: {error}") from error
    raise SsoError(f"Unsupported key type {jwk.get('kty')}")


def _verify_signature(algorithm: str, key, signed: bytes, signature: bytes) -> None:
    digest = _HASHES.get(algorithm[2:])
    try:
        if algorithm.startswith("RS") and isinstance(key, rsa.RSAPublicKey) and digest:
            key.verify(signature, signed, padding.PKCS1v15(), digest())
        elif algorithm.startswith("ES") and isinstance(key, ec.EllipticCurvePublicKey) and digest:
            size = (key.curve.key_size + 7) // 8
            if len(signature) != 2 * size:
                raise SsoError("Malformed ID token signature")
            r, s = int.from_bytes(signature[:size]), int.from_bytes(signature[size:])
            key.verify(encode_dss_signature(r, s), signed, ec.ECDSA(digest()))
        else:
            raise SsoError(f"The ID token uses an unsupported signature ({algorithm})")
    except InvalidSignature as error:
        raise SsoError("The signature of the ID token is wrong") from error


async def _signing_key(jwks_uri: str, header: dict):
    for attempt in range(2):
        # A key the cache does not know may be a new one: load the set again once.
        keys = (await _get_json(jwks_uri, force=attempt == 1)).get("keys", [])
        kid = header.get("kid")
        matching = [k for k in keys if isinstance(k, dict) and k.get("use", "sig") == "sig" and k.get("kid") == kid]
        if matching:
            return _public_key(matching[0])
    raise SsoError("The ID token is signed with an unknown key")


async def verify_id_token(token: str, nonce: str) -> dict:
    """The claims of an ID token from the token endpoint, if signature, issuer, audience, expiry and nonce are right."""
    try:
        head, body, signature = token.split(".")
        header, claims = json.loads(_b64decode(head)), json.loads(_b64decode(body))
        signature = _b64decode(signature)
    except ValueError as error:
        raise SsoError("The ID token is malformed") from error
    if not isinstance(header, dict) or not isinstance(claims, dict):
        raise SsoError("The ID token is malformed")

    document = await discovery()
    key = await _signing_key(document["jwks_uri"], header)
    _verify_signature(str(header.get("alg", "")), key, f"{head}.{body}".encode(), signature)

    if str(claims.get("iss", "")).rstrip("/") != settings.OIDC_ISSUER.rstrip("/"):
        raise SsoError("The ID token comes from another issuer")
    audience = claims.get("aud")
    audiences = [audience] if isinstance(audience, str) else audience
    if not isinstance(audiences, list) or settings.OIDC_CLIENT_ID not in audiences:
        raise SsoError("The ID token is not meant for this app")
    if len(audiences) > 1 and claims.get("azp") != settings.OIDC_CLIENT_ID:
        raise SsoError("The ID token was issued to another app")
    now = time.time()
    if not isinstance(claims.get("exp"), int | float) or claims["exp"] + LEEWAY < now:
        raise SsoError("The ID token has expired")
    if isinstance(claims.get("iat"), int | float) and claims["iat"] - LEEWAY > now:
        raise SsoError("The ID token was issued in the future")
    if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise SsoError("The nonce of the ID token does not match")
    if not claims.get("sub"):
        raise SsoError("The ID token has no subject")
    return claims


async def exchange_code(code: str, redirect_uri: str, verifier: str) -> str:
    """Trade the authorization code for tokens and return the ID token."""
    document = await discovery()
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": verifier,
        "client_id": settings.OIDC_CLIENT_ID,
    }
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.post(
                document["token_endpoint"],
                data=data,
                auth=(_form(settings.OIDC_CLIENT_ID), _form(settings.OIDC_CLIENT_SECRET)),
            )
            tokens = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise SsoError(f"The token request failed: {error}") from error
    if response.status_code != 200 or not isinstance(tokens, dict) or not tokens.get("id_token"):
        error = tokens.get("error") if isinstance(tokens, dict) else ""
        raise SsoError(f"The provider refused the code ({response.status_code} {error})")
    return tokens["id_token"]


def _form(value: str) -> str:
    """Client credentials in the Basic header are form-encoded first (RFC 6749 section 2.3.1)."""
    return quote_plus(value)


@dataclass
class Profile:
    subject: str
    email: str
    email_verified: bool
    username: str
    first_name: str
    last_name: str

    @classmethod
    def from_claims(cls, claims: dict) -> Profile:
        def text(name: str) -> str:
            value = claims.get(name)
            return value.strip() if isinstance(value, str) else ""

        first, last = text("given_name"), text("family_name")
        if not (first or last) and (name := text("name")):
            first, _, last = name.partition(" ")
        return cls(
            subject=str(claims["sub"]),
            email=text("email").lower(),
            email_verified=claims.get("email_verified") is True,
            username=text("preferred_username") or text("email").partition("@")[0],
            first_name=first,
            last_name=last,
        )


async def find_or_create_user(profile: Profile) -> User:
    """The user who belongs to the provider's account.

    Known accounts are found by issuer and ``sub``. A first sign-in is matched to an existing user by an e-mail
    address the provider says it has verified (nobody can claim an address by typing it in at the provider).
    Without a match an account is created only if ``APP_OIDC_CREATE_USERS`` allows it.
    """
    issuer = settings.OIDC_ISSUER.rstrip("/")
    identity = await SsoIdentity.objects.select_related("user").filter(issuer=issuer, subject=profile.subject).afirst()
    if identity is not None:
        if not identity.user.is_active:
            raise SsoError(f"The account of {identity.user.get_username()} is deactivated")
        return identity.user

    if not (profile.email and profile.email_verified):
        raise NoAccount("The provider sent no verified e-mail address to find the account by")
    matches = [user async for user in User.objects.filter(email__iexact=profile.email)[:2]]
    if len(matches) > 1:
        raise SsoError(f"More than one account has the address {profile.email}")
    if matches:
        user = matches[0]
        if not user.is_active:
            raise SsoError(f"The account of {user.get_username()} is deactivated")
    elif not settings.OIDC_CREATE_USERS:
        raise NoAccount(f"No account for {profile.email} and APP_OIDC_CREATE_USERS is off")
    else:
        domain = profile.email.rpartition("@")[2]
        if settings.OIDC_ALLOWED_EMAIL_DOMAINS and domain not in settings.OIDC_ALLOWED_EMAIL_DOMAINS:
            raise NoAccount(f"The domain of {profile.email} may not create an account")
        user = await _create_user(profile)

    # If the same sign-in finished in another request first, the link exists already.
    with suppress(IntegrityError):
        await SsoIdentity.objects.acreate(user=user, issuer=issuer, subject=profile.subject)
    return user


async def _create_user(profile: Profile) -> User:
    base = (profile.username or "user")[:140]
    username = base
    suffix = 1
    while await User.objects.filter(username__iexact=username).aexists():
        suffix += 1
        username = f"{base}{suffix}"
    user = User(
        username=username,
        email=profile.email,
        first_name=profile.first_name[:150],
        last_name=profile.last_name[:150],
        role=User.Role.EMPLOYEE,
    )
    user.set_unusable_password()
    await user.asave()
    return user
