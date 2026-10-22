import httpx
import pytest

from lexware.client import LexwareClient, LexwareError
from lexware.schemas import Contact
from tests.lexware_fakes import contact, fake_client, page, serve_pages


async def collect(client: LexwareClient) -> list[Contact]:
    async with client:
        return [c async for c in client.iter_customers()]


async def test_reads_all_pages_with_auth_header():
    handler = serve_pages(
        page([contact("A")], number=0, total_pages=2),
        page([contact("B")], number=1, total_pages=2),
    )

    contacts = await collect(fake_client(handler))

    assert [c.name for c in contacts] == ["A", "B"]
    assert [r.url.params["page"] for r in handler.requests] == ["0", "1"]
    assert handler.requests[0].url.params["customer"] == "true"
    assert handler.requests[0].headers["Authorization"] == "Bearer test-key"


async def test_retries_after_rate_limit():
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json=page([contact()]))

    contacts = await collect(fake_client(handler))

    assert len(contacts) == 1
    assert len(calls) == 2


async def test_rejected_api_key_raises():
    with pytest.raises(LexwareError, match="API-Schlüssel"):
        await collect(fake_client(lambda request: httpx.Response(401)))


def test_missing_api_key_raises():
    with pytest.raises(LexwareError):
        LexwareClient("")


def test_contact_fields_for_person_and_company():
    person = Contact.model_validate(
        contact(
            company=None,
            person={"firstName": "Erika", "lastName": "Muster"},
            emailAddresses={"private": ["erika@example.de"]},
            phoneNumbers={"mobile": ["0170 123"]},
        )
    )
    company = Contact.model_validate(
        contact(
            company={
                "name": "ACME GmbH",
                "contactPersons": [{"emailAddress": "a@acme.de"}, {"emailAddress": "b@acme.de", "primary": True}],
            }
        )
    )

    assert (person.name, person.email, person.phone) == ("Erika Muster", "erika@example.de", "0170 123")
    assert (company.name, company.email, company.customer_number) == ("ACME GmbH", "b@acme.de", "10001")
