"""The app's name and logo, which an administrator can replace on the settings page.

Without a name the app is called ``DEFAULT_NAME`` and without an uploaded logo it shows the built-in mark.
Pages get the brand as ``brand`` (a context processor reading what ``BrandingMiddleware`` loaded);
e-mails get it from ``mailer.outbox.aqueue``.
"""

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from xml.etree import ElementTree

from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.urls import reverse
from django.utils.decorators import async_only_middleware
from django.utils.translation import gettext_lazy as _

from core.models import AppSettings

DEFAULT_NAME = "LexTracker"
NAME_MAX_LENGTH = 40
LOGO_MAX_SIZE = 256 * 1024
# Not loaded for requests that never render a page.
SKIPPED = ("/static/", "/mcp/", "/health/", "/robots.txt")

_RASTER_SIGNATURES = {
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
}
# External entities and entity expansion have no place in a logo.
_DANGEROUS_XML = re.compile(rb"<!(DOCTYPE|ENTITY)", re.IGNORECASE)


@dataclass(frozen=True)
class Brand:
    name: str = DEFAULT_NAME
    logo_url: str = ""
    logo_type: str = ""


def _brand(row: dict | None) -> Brand:
    if not row:
        return Brand()
    logo_url = ""
    if row["logo_type"] and row["logo_updated_at"]:
        # The timestamp in the URL lets browsers cache the logo for good and still show a new one at once.
        logo_url = f"{reverse('core:logo')}?v={int(row['logo_updated_at'].timestamp())}"
    return Brand(name=row["app_name"] or DEFAULT_NAME, logo_url=logo_url, logo_type=row["logo_type"])


def _query():
    # Not the logo itself: this runs for every page.
    return AppSettings.objects.filter(pk=1).values("app_name", "logo_type", "logo_updated_at")


def load() -> Brand:
    return _brand(_query().first())


async def aload() -> Brand:
    return _brand(await _query().afirst())


def sniff_logo(data: bytes) -> str | None:
    """The content type of a PNG, JPEG, WebP or SVG image, or None for anything else.

    Judged by the content, not by the file name or the type the browser sent.
    """
    for signature, content_type in _RASTER_SIGNATURES.items():
        if data.startswith(signature):
            return content_type
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if _DANGEROUS_XML.search(data):
        return None
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError:
        return None
    return "image/svg+xml" if root.tag.rpartition("}")[2] == "svg" else None


def read_logo(file) -> tuple[bytes, str]:
    """The bytes and content type of an uploaded logo. Raises ValidationError if it is not usable."""
    if file.size > LOGO_MAX_SIZE:
        raise ValidationError(_("Das Logo ist größer als %(size)s KB."), params={"size": LOGO_MAX_SIZE // 1024})
    data = file.read()
    content_type = sniff_logo(data)
    if content_type is None:
        raise ValidationError(_("Das Logo muss ein PNG, JPEG, WebP oder SVG sein."))
    return data, content_type


@async_only_middleware
def BrandingMiddleware(get_response: Callable[[HttpRequest], Awaitable[HttpResponse]]):
    """Load the name and logo once per request, since a template must not query the database in an async view."""

    async def middleware(request: HttpRequest) -> HttpResponse:
        if not request.path.startswith(SKIPPED):
            request.brand = await aload()
        return await get_response(request)

    return middleware


def context(request: HttpRequest) -> dict:
    """Context processor: ``{{ brand.name }}`` and ``{% logo %}`` in every page."""
    return {"brand": getattr(request, "brand", None) or Brand()}
