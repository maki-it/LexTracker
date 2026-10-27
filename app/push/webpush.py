"""Web Push (RFC 8030) with the VAPID signature (RFC 8292) and the encryption of RFC 8291 (``aes128gcm``).

Written with ``cryptography`` and ``httpx``, which the app uses anyway, so it needs no library of its own and
sends without blocking. Only what the app needs: a small JSON message to one subscription.
"""

import base64
import json
import os
import struct
import time
from urllib.parse import urlsplit

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

# One record of the encrypted message holds this much; the messages of the app are far smaller.
RECORD_SIZE = 4096
# A VAPID signature is valid for up to a day; push services reject a longer one.
VAPID_LIFETIME = 12 * 3600
# How long the push service keeps a message for a device that is offline. A reminder that arrives a day late is
# still useful, a running-timer notification from yesterday is not (see ``ttl`` of ``send``).
DEFAULT_TTL = 24 * 3600
TIMEOUT = 10


class PushGone(Exception):
    """The push service says the subscription does not exist anymore (the user revoked it or uninstalled the app)."""


class PushError(Exception):
    """The push service did not take the message."""


def b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def new_private_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


def public_bytes(key: ec.EllipticCurvePrivateKey | ec.EllipticCurvePublicKey) -> bytes:
    """The public key as the uncompressed point (65 bytes), which is what browsers and push services use."""
    public = key.public_key() if isinstance(key, ec.EllipticCurvePrivateKey) else key
    return public.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def private_pem(key: ec.EllipticCurvePrivateKey) -> str:
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()


def load_private(pem: str) -> ec.EllipticCurvePrivateKey:
    key = serialization.load_pem_private_key(pem.encode(), password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey):
        raise ValueError("Not an elliptic curve key")
    return key


def encrypt(payload: bytes, p256dh: str, auth: str) -> bytes:
    """The message as the browser's push service gets it: header with salt and our key, then the ciphertext."""
    receiver = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), b64decode(p256dh))
    receiver_bytes = public_bytes(receiver)
    sender = new_private_key()
    sender_bytes = public_bytes(sender)
    salt = os.urandom(16)
    shared = sender.exchange(ec.ECDH(), receiver)
    key_info = b"WebPush: info\x00" + receiver_bytes + sender_bytes
    secret = HKDF(hashes.SHA256(), 32, b64decode(auth), key_info).derive(shared)
    content_key = HKDF(hashes.SHA256(), 16, salt, b"Content-Encoding: aes128gcm\x00").derive(secret)
    nonce = HKDF(hashes.SHA256(), 12, salt, b"Content-Encoding: nonce\x00").derive(secret)
    # 0x02 marks the last (and only) record.
    ciphertext = AESGCM(content_key).encrypt(nonce, payload + b"\x02", None)
    return salt + struct.pack(">IB", RECORD_SIZE, len(sender_bytes)) + sender_bytes + ciphertext


def decrypt(body: bytes, private_key: ec.EllipticCurvePrivateKey, auth: str) -> bytes:
    """What the browser does with a message; here for the tests."""
    salt, key_length = body[:16], body[20]
    sender_bytes, ciphertext = body[21 : 21 + key_length], body[21 + key_length :]
    sender = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), sender_bytes)
    shared = private_key.exchange(ec.ECDH(), sender)
    key_info = b"WebPush: info\x00" + public_bytes(private_key) + sender_bytes
    secret = HKDF(hashes.SHA256(), 32, b64decode(auth), key_info).derive(shared)
    content_key = HKDF(hashes.SHA256(), 16, salt, b"Content-Encoding: aes128gcm\x00").derive(secret)
    nonce = HKDF(hashes.SHA256(), 12, salt, b"Content-Encoding: nonce\x00").derive(secret)
    plain = AESGCM(content_key).decrypt(nonce, ciphertext, None)
    return plain[: plain.rindex(b"\x02")]


def vapid_header(endpoint: str, private_key: ec.EllipticCurvePrivateKey, subject: str, now: float | None = None) -> str:
    """The ``Authorization`` header that proves to the push service that the message comes from this app."""
    parts = urlsplit(endpoint)
    claims = {
        "aud": f"{parts.scheme}://{parts.netloc}",
        "exp": int((now or time.time()) + VAPID_LIFETIME),
        "sub": subject,
    }
    signing_input = ".".join(
        b64encode(json.dumps(part, separators=(",", ":")).encode()) for part in ({"typ": "JWT", "alg": "ES256"}, claims)
    )
    r, s = decode_dss_signature(private_key.sign(signing_input.encode(), ec.ECDSA(hashes.SHA256())))
    signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    return f"vapid t={signing_input}.{b64encode(signature)}, k={b64encode(public_bytes(private_key))}"


async def send(
    client: httpx.AsyncClient,
    endpoint: str,
    p256dh: str,
    auth: str,
    message: dict,
    *,
    private_key: ec.EllipticCurvePrivateKey,
    subject: str,
    ttl: int = DEFAULT_TTL,
    urgency: str = "normal",
) -> None:
    """Send the message (a dict, sent as JSON) to one browser. Raises ``PushGone`` or ``PushError``."""
    body = encrypt(json.dumps(message, separators=(",", ":")).encode(), p256dh, auth)
    headers = {
        "Authorization": vapid_header(endpoint, private_key, subject),
        "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream",
        "TTL": str(ttl),
        "Urgency": urgency,
    }
    try:
        response = await client.post(endpoint, content=body, headers=headers)
    except httpx.HTTPError as error:
        raise PushError(f"{type(error).__name__}: {error}") from error
    if response.status_code in (404, 410):
        raise PushGone(endpoint)
    if response.status_code >= 300:
        raise PushError(f"HTTP {response.status_code}: {response.text[:200]}")
