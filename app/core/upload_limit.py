"""Refuse oversized backup uploads before Django reads them.

Django's ASGI handler reads the whole request body into a temporary file before any middleware or view
runs, and in Docker /tmp lives in memory. So the size has to be checked here, from the Content-Length
header. Browsers always send it for a form; a request without it is refused too.
"""

from django.conf import settings
from django.urls import reverse

# Room for the multipart boundaries and the CSRF field around the file itself.
FORM_OVERHEAD = 64 * 1024


class LimitBackupUpload:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] == "POST" and scope["path"] == reverse("core:backup_upload"):
            length = dict(scope["headers"]).get(b"content-length", b"")
            if not length.isdigit() or int(length) > settings.BACKUP_UPLOAD_MAX_SIZE + FORM_OVERHEAD:
                await send(
                    {
                        "type": "http.response.start",
                        "status": 413,
                        "headers": [(b"content-type", b"text/plain; charset=utf-8")],
                    }
                )
                await send({"type": "http.response.body", "body": "Die Datei ist zu groß.".encode()})
                return
        await self.app(scope, receive, send)
