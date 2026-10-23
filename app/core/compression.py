"""Compress pages with Brotli or gzip, whichever the browser accepts (Brotli first).

Static files are not handled here: ServeStatic serves them already compressed.
"""

import gzip
import re
from collections.abc import Awaitable, Callable

import brotli
from django.http import HttpRequest, HttpResponse
from django.utils.cache import patch_vary_headers
from django.utils.decorators import async_only_middleware

# Smaller responses do not get noticeably smaller, compressing them only costs time.
MIN_SIZE = 500
COMPRESSIBLE = ("text/", "application/json", "application/javascript", "image/svg+xml")
# Fast levels: most of the gain for little CPU, which is what limits the app (see loadtest/).
BROTLI_QUALITY = 4
GZIP_LEVEL = 6


def _accepts(request: HttpRequest, encoding: str) -> bool:
    return bool(re.search(rf"\b{encoding}\b", request.headers.get("accept-encoding", "")))


def compress(request: HttpRequest, response: HttpResponse) -> HttpResponse:
    if (
        response.streaming
        or response.has_header("Content-Encoding")
        or len(response.content) < MIN_SIZE
        or not response.get("Content-Type", "").startswith(COMPRESSIBLE)
    ):
        return response
    patch_vary_headers(response, ("Accept-Encoding",))
    if _accepts(request, "br"):
        content, encoding = brotli.compress(response.content, quality=BROTLI_QUALITY), "br"
    elif _accepts(request, "gzip"):
        content, encoding = gzip.compress(response.content, compresslevel=GZIP_LEVEL, mtime=0), "gzip"
    else:
        return response
    if len(content) >= len(response.content):
        return response
    response.content = content
    response["Content-Length"] = str(len(content))
    response["Content-Encoding"] = encoding
    # A weak ETag stays valid for the compressed body, a strong one would not.
    if (etag := response.get("ETag", "")).startswith('"'):
        response["ETag"] = "W/" + etag
    return response


@async_only_middleware
def CompressionMiddleware(get_response: Callable[[HttpRequest], Awaitable[HttpResponse]]):
    async def middleware(request: HttpRequest) -> HttpResponse:
        return compress(request, await get_response(request))

    return middleware
