import asyncio

from pydantic import UUID4
from httpx import AsyncClient
from httpx_limiter import AsyncRateLimitedTransport

from .config import get_config
from .models import Customer


class PageSizeLimits:
  # https://developers.lexoffice.io/docs/#paging-of-resources
  CONTACTS = 250


class ApiClient:
  def __init__(self):
    config = get_config()
    self.opts = dict(
      base_url=config.endpoint,
      headers={
        'Authorization': f'Bearer {config.token}',
        'Accept': 'application/json',
        'Content-Type': 'application/json'
      },
      transport=AsyncRateLimitedTransport.create(
        rate=config.requests_per_seconds,
        capacity=config.requests_per_seconds - 1
      )
    )

  async def get_customers(self, customer_id: UUID4 = None) -> list | dict:
    """
    Returns customers from Lexoffice API
    :param customer_id: If provided, returns a single customer, otherwise returns all customers
    :return: Any
    """

    async def get(c: AsyncClient, page: int) -> dict:
      resp = await c.get(path,
        params={
          'size': PageSizeLimits.CONTACTS,
          'page': page,
          'customer': True,
          'vendor': False},
        headers=[('Connection', 'close')]
      )
      resp.raise_for_status()
      return resp.json()

    path = f'/contacts/{customer_id}' if customer_id else '/contacts'

    async with AsyncClient(**self.opts) as client:
      data = await get(client, page=0)

      if customer_id:
        return data

      customers = data.get("content")

      # Fetch data from remaining pages
      for data in await asyncio.gather(*[get(page) for page in range(1, data.get("totalPages"))]):
        customers.extend(data.get("content"))

    return customers


api_client = ApiClient()


async def save_customer(customer: dict) -> Customer | None:
  customer_obj, created = await Customer.objects.aget_or_create(
    id=customer["id"],
    organization_id=customer["organizationId"],
    number=customer["roles"]["customer"]["number"],
  )

  latest_version = customer["version"]

  if created or customer_obj.version < latest_version:
    customer_obj.version = latest_version
    customer_obj.is_archived = customer["archived"]

    try:
      # Company
      customer_obj.name = customer["company"]["name"]
      customer_obj.type = Customer.CustomerType.COMPANY
    except KeyError:
      # Person
      customer_obj.name = " ".join([customer["person"]["firstName"], customer["person"]["lastName"]])
      customer_obj.type = Customer.CustomerType.PERSON

    await customer_obj.asave()
    return customer_obj
