import asyncio
import logging
import time
from collections.abc import AsyncIterator
from datetime import date
from types import TracebackType
from typing import Self
from uuid import UUID

import httpx

from lexware.schemas import Contact, ContactPage, Profile, Voucher, VoucherPage

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.lexware.io/v1/"
# The API allows 2 requests per second. Larger pages mean fewer requests.
REQUESTS_PER_SECOND = 2
CONTACTS_PAGE_SIZE = 250
VOUCHERS_PAGE_SIZE = 250
MAX_RETRIES = 3


def _error_detail(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text[:200]
    details = data.get("details") or []
    messages = [f"{d.get('field', '')}: {d.get('message', '')}".strip(": ") for d in details]
    return "; ".join(messages) or data.get("message") or str(data)[:200]


class LexwareError(Exception):
    """The Lexware Office API could not be reached or answered with an error."""


class LexwareNotFound(LexwareError):
    """Lexware does not know the requested resource (HTTP 404), for example a deleted draft."""


def client_from_settings() -> LexwareClient:
    from django.conf import settings

    return LexwareClient(settings.LEXWARE_API_KEY, base_url=settings.LEXWARE_BASE_URL)


class LexwareClient:
    """Async client for the Lexware Office Public API.

    Use as ``async with LexwareClient(api_key) as client: ...``. Requests are spaced
    out to stay under the API's rate limit, and answers with HTTP 429 are retried.
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        requests_per_second: float = REQUESTS_PER_SECOND,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise LexwareError("Es ist kein Lexware-API-Schlüssel hinterlegt (APP_LEXWARE_API_KEY).")
        self._http = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            timeout=httpx.Timeout(15.0),
            transport=transport,
        )
        self._min_interval = 1 / requests_per_second if requests_per_second else 0.0
        self._last_request = 0.0
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        await self._http.aclose()

    async def _wait_for_slot(self) -> None:
        async with self._lock:
            delay = self._last_request + self._min_interval - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            self._last_request = time.monotonic()

    async def _request(self, method: str, path: str, params: dict | None = None, json: dict | None = None) -> dict:
        return (await self._send(method, path, params=params, json=json)).json()

    async def _send(
        self, method: str, path: str, *, params: dict | None = None, json: dict | None = None, accept: str | None = None
    ) -> httpx.Response:
        headers = {"Accept": accept} if accept else None
        for attempt in range(MAX_RETRIES + 1):
            await self._wait_for_slot()
            try:
                response = await self._http.request(method, path, params=params, json=json, headers=headers)
            except httpx.HTTPError as exc:
                raise LexwareError(f"Lexware ist nicht erreichbar: {exc}") from exc

            if response.status_code == httpx.codes.TOO_MANY_REQUESTS and attempt < MAX_RETRIES:
                retry_after = float(response.headers.get("Retry-After", 1))
                logger.info("Lexware rate limit hit, retrying in %.1fs", retry_after)
                await asyncio.sleep(retry_after)
                continue
            if response.status_code == httpx.codes.UNAUTHORIZED:
                raise LexwareError("Lexware hat den API-Schlüssel abgelehnt.")
            if response.status_code == httpx.codes.NOT_FOUND:
                raise LexwareNotFound(f"Lexware kennt {path} nicht (HTTP 404).")
            if response.is_error:
                raise LexwareError(f"Lexware antwortete mit HTTP {response.status_code}: {_error_detail(response)}")
            return response
        raise LexwareError("Lexware hat zu viele Anfragen abgelehnt (Rate-Limit).")

    async def get_profile(self) -> Profile:
        return Profile.model_validate(await self._request("GET", "profile"))

    async def create_invoice(self, payload: dict) -> UUID:
        """Create an invoice draft (not finalized) and return its ID."""
        data = await self._request("POST", "invoices", json=payload)
        return UUID(data["id"])

    async def get_invoice(self, invoice_id: UUID) -> dict:
        """The invoice as Lexware returns it. Raises LexwareNotFound if it was deleted."""
        return await self._request("GET", f"invoices/{invoice_id}")

    async def get_invoice_pdf(self, invoice_id: UUID) -> bytes:
        """The finalized invoice as PDF. Drafts have none."""
        response = await self._send("GET", f"invoices/{invoice_id}/file", accept="application/pdf")
        return response.content

    async def iter_invoices(self, *, created_from: date | None = None) -> AsyncIterator[Voucher]:
        """Yield the invoices in the voucher list, in every status, page by page."""
        page = 0
        while True:
            params = {"voucherType": "invoice", "voucherStatus": "any", "page": page, "size": VOUCHERS_PAGE_SIZE}
            if created_from:
                params["createdDateFrom"] = created_from.isoformat()
            result = VoucherPage.model_validate(await self._request("GET", "voucherlist", params))
            for voucher in result.content:
                yield voucher
            if result.last or page + 1 >= result.total_pages:
                return
            page += 1

    async def get_contact(self, contact_id: UUID) -> dict:
        """The full contact as Lexware returns it, so it can be changed and sent back."""
        return await self._request("GET", f"contacts/{contact_id}")

    async def update_contact(self, contact_id: UUID, contact: dict) -> int:
        """Replace the contact and return its new version.

        ``contact`` must carry the current ``version``, otherwise Lexware rejects the change.
        """
        data = await self._request("PUT", f"contacts/{contact_id}", json=contact)
        return data["version"]

    async def iter_customers(self) -> AsyncIterator[Contact]:
        """Yield every contact that has the customer role, page by page."""
        page = 0
        while True:
            params = {"customer": "true", "page": page, "size": CONTACTS_PAGE_SIZE}
            data = await self._request("GET", "contacts", params)
            result = ContactPage.model_validate(data)
            for contact in result.content:
                yield contact
            if result.last or page + 1 >= result.total_pages:
                return
            page += 1
