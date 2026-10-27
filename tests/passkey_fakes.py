"""A fake authenticator for the passkey tests: makes the answers a browser would send, signed with a real key."""

import hashlib
import json
import os

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url

RP_ID = "zeit.example.de"
ORIGIN = "https://zeit.example.de"

USER_PRESENT, USER_VERIFIED, BACKUP_ELIGIBLE, BACKED_UP, ATTESTED = 0x01, 0x04, 0x08, 0x10, 0x40


class Authenticator:
    def __init__(self, *, rp_id: str = RP_ID, origin: str = ORIGIN, synced: bool = False):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = os.urandom(32)
        self.rp_id = rp_id
        self.origin = origin
        self.synced = synced
        self.sign_count = 0

    def _client_data(self, kind: str, challenge: str, origin: str | None = None) -> bytes:
        data = {"type": kind, "challenge": challenge, "origin": origin or self.origin, "crossOrigin": False}
        return json.dumps(data).encode()

    def _flags(self, *, verified: bool, attested: bool = False) -> int:
        flags = USER_PRESENT
        flags |= USER_VERIFIED if verified else 0
        flags |= ATTESTED if attested else 0
        flags |= (BACKUP_ELIGIBLE | BACKED_UP) if self.synced else 0
        return flags

    def _auth_data(self, *, verified: bool, attested: bool = False) -> bytes:
        return (
            hashlib.sha256(self.rp_id.encode()).digest()
            + bytes([self._flags(verified=verified, attested=attested)])
            + self.sign_count.to_bytes(4, "big")
        )

    def _cose_key(self) -> bytes:
        numbers = self.key.public_key().public_numbers()
        x, y = numbers.x.to_bytes(32, "big"), numbers.y.to_bytes(32, "big")
        return cbor2.dumps({1: 2, 3: -7, -1: 1, -2: x, -3: y})

    def register(self, options: dict, *, verified: bool = True, origin: str | None = None) -> dict:
        """The answer to ``navigator.credentials.create`` for the options the server sent."""
        client_data = self._client_data("webauthn.create", options["challenge"], origin)
        credential = bytes(16) + len(self.credential_id).to_bytes(2, "big") + self.credential_id + self._cose_key()
        auth_data = self._auth_data(verified=verified, attested=True) + credential
        attestation = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        credential_id = bytes_to_base64url(self.credential_id)
        return {
            "id": credential_id,
            "rawId": credential_id,
            "type": "public-key",
            "authenticatorAttachment": "platform",
            "clientExtensionResults": {},
            "response": {
                "clientDataJSON": bytes_to_base64url(client_data),
                "attestationObject": bytes_to_base64url(attestation),
                "transports": ["internal"],
            },
        }

    def sign_in(
        self, options: dict, *, user_handle: bytes | None = None, verified: bool = True, origin: str | None = None
    ) -> dict:
        """The answer to ``navigator.credentials.get`` for the options the server sent."""
        self.sign_count += 1
        client_data = self._client_data("webauthn.get", options["challenge"], origin)
        auth_data = self._auth_data(verified=verified)
        signed = auth_data + hashlib.sha256(client_data).digest()
        signature = self.key.sign(signed, ec.ECDSA(hashes.SHA256()))
        credential_id = bytes_to_base64url(self.credential_id)
        return {
            "id": credential_id,
            "rawId": credential_id,
            "type": "public-key",
            "authenticatorAttachment": "platform",
            "clientExtensionResults": {},
            "response": {
                "clientDataJSON": bytes_to_base64url(client_data),
                "authenticatorData": bytes_to_base64url(auth_data),
                "signature": bytes_to_base64url(signature),
                "userHandle": bytes_to_base64url(user_handle) if user_handle else None,
            },
        }


def challenge_bytes(options: dict) -> bytes:
    return base64url_to_bytes(options["challenge"])
