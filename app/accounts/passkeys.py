"""Sign in with passkeys (WebAuthn), for the phone as well as the desktop.

Configured with ``APP_PASSKEY_RP_ID``: a passkey belongs to that domain for good, so it is set once and not changed.
The login with password, the e-mail link and SSO stay. A passkey is checked with the user's fingerprint, face or PIN
(user verification is required), so it counts as both factors and skips the code from an authenticator app.

The two steps of each ceremony are split in two functions: ``begin_*`` makes the options for the browser and the
state to remember (in the session) and ``finish_*`` checks the browser's answer against that state. The functions
query the database synchronously; call them with ``sync_to_async``.
"""

import time
from dataclasses import dataclass

from django.conf import settings
from django.utils import timezone
from webauthn import (
    base64url_to_bytes,
    generate_authentication_options,
    generate_registration_options,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import (
    bytes_to_base64url,
    options_to_json_dict,
    parse_authentication_credential_json,
    parse_registration_credential_json,
)
from webauthn.helpers.exceptions import InvalidAuthenticationResponse, InvalidJSONStructure, InvalidRegistrationResponse
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    CredentialDeviceType,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from accounts.models import Passkey, User

# How long the browser has to answer, in the session and for the browser's own prompt.
CHALLENGE_SECONDS = 300
NAME_MAX_LENGTH = 100


class PasskeyError(Exception):
    """The browser's answer is not valid, or too late."""


def enabled() -> bool:
    return bool(settings.PASSKEY_RP_ID)


@dataclass(frozen=True)
class Begun:
    """What a ceremony starts with: ``options`` go to the browser, ``state`` stays in the session."""

    options: dict
    state: dict


def _state(challenge: bytes, **extra) -> dict:
    return {"challenge": bytes_to_base64url(challenge), "at": time.time(), **extra}


def _challenge_of(state: dict | None) -> bytes:
    if not state or time.time() - state["at"] > CHALLENGE_SECONDS:
        raise PasskeyError("Unknown or expired passkey attempt")
    return base64url_to_bytes(state["challenge"])


def begin_registration(user: User, app_name: str) -> Begun:
    existing = [PublicKeyCredentialDescriptor(id=base64url_to_bytes(p.credential_id)) for p in user.passkeys.all()]
    options = generate_registration_options(
        rp_id=settings.PASSKEY_RP_ID,
        rp_name=app_name,
        user_id=user.pk.bytes,
        user_name=user.get_username(),
        user_display_name=user.get_full_name() or user.get_username(),
        # Keeps the browser from offering a device that already has a passkey for this account.
        exclude_credentials=existing,
        # A discoverable credential, so that signing in needs no username; checked with fingerprint, face or PIN.
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED, user_verification=UserVerificationRequirement.REQUIRED
        ),
        timeout=CHALLENGE_SECONDS * 1000,
    )
    return Begun(options_to_json_dict(options), _state(options.challenge, user=str(user.pk)))


def finish_registration(user: User, credential: dict, state: dict | None, name: str) -> Passkey:
    challenge = _challenge_of(state)
    if state.get("user") != str(user.pk):
        raise PasskeyError("The attempt belongs to another account")
    try:
        verified = verify_registration_response(
            credential=parse_registration_credential_json(credential),
            expected_challenge=challenge,
            expected_rp_id=settings.PASSKEY_RP_ID,
            expected_origin=settings.PASSKEY_ORIGINS,
            require_user_verification=True,
        )
    except (InvalidRegistrationResponse, InvalidJSONStructure, KeyError, TypeError, ValueError) as error:
        raise PasskeyError(str(error)) from error
    credential_id = bytes_to_base64url(verified.credential_id)
    if Passkey.objects.filter(credential_id=credential_id).exists():
        raise PasskeyError("This passkey is already registered")
    return Passkey.objects.create(
        user=user,
        name=name.strip()[:NAME_MAX_LENGTH] or "Passkey",
        credential_id=credential_id,
        public_key=verified.credential_public_key,
        sign_count=verified.sign_count,
        synced=verified.credential_device_type == CredentialDeviceType.MULTI_DEVICE,
    )


def begin_authentication() -> Begun:
    options = generate_authentication_options(
        rp_id=settings.PASSKEY_RP_ID,
        # No list of credentials: the browser offers the passkeys it has for this domain, whoever they belong to.
        user_verification=UserVerificationRequirement.REQUIRED,
        timeout=CHALLENGE_SECONDS * 1000,
    )
    return Begun(options_to_json_dict(options), _state(options.challenge))


def finish_authentication(credential: dict, state: dict | None) -> User:
    """The user whose passkey signed the challenge. Raises ``PasskeyError`` for anything else."""
    challenge = _challenge_of(state)
    try:
        parsed = parse_authentication_credential_json(credential)
        passkey = Passkey.objects.select_related("user").get(credential_id=bytes_to_base64url(parsed.raw_id))
        verified = verify_authentication_response(
            credential=parsed,
            expected_challenge=challenge,
            expected_rp_id=settings.PASSKEY_RP_ID,
            expected_origin=settings.PASSKEY_ORIGINS,
            credential_public_key=bytes(passkey.public_key),
            credential_current_sign_count=passkey.sign_count,
            require_user_verification=True,
        )
    except (
        Passkey.DoesNotExist,
        InvalidAuthenticationResponse,
        InvalidJSONStructure,
        KeyError,
        TypeError,
        ValueError,
    ) as error:
        raise PasskeyError(str(error)) from error
    if not passkey.user.is_active:
        raise PasskeyError("The account is not active")
    passkey.sign_count = verified.new_sign_count
    passkey.last_used_at = timezone.now()
    passkey.save(update_fields=["sign_count", "last_used_at"])
    return passkey.user
