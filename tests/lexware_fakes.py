"""A fake Lexware Office API for tests, built on httpx.MockTransport."""

import uuid

import httpx

from lexware.client import LexwareClient


def contact(name: str = "ACME GmbH", *, number: int = 10001, version: int = 1, **extra) -> dict:
    data = {
        "id": str(extra.pop("id", uuid.uuid4())),
        "version": version,
        "archived": False,
        "roles": {"customer": {"number": number}},
        "company": {"name": name},
    }
    data.update(extra)
    return data


def page(contacts: list[dict], number: int = 0, total_pages: int = 1) -> dict:
    return {
        "content": contacts,
        "number": number,
        "totalPages": total_pages,
        "last": number + 1 >= total_pages,
    }


def fake_client(handler) -> LexwareClient:
    return LexwareClient("test-key", requests_per_second=0, transport=httpx.MockTransport(handler))


def serve_pages(*pages: dict):
    """A handler that returns the given pages by their ?page= parameter."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=pages[int(request.url.params["page"])])

    handler.requests = requests
    return handler
