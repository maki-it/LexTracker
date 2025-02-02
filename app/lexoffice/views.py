import asyncio

from pydantic import UUID4
from django.http import HttpResponse

from .utils import api_client, save_customer

# Create your views here.

async def sync_customer(request, customer_id: UUID4):
  """
  Sync a single customer from Lexoffice API to local database
  :param request:
  :param customer_id: ID of the customer to sync
  :return:
  """
  customer = await api_client.get_customers(customer_id)
  await save_customer(customer)
  return HttpResponse(status=201, content="Customer synced successfully")


async def sync_customers(request):
  """
  Sync customers from Lexoffice API to local database
  :param request:
  :return:
  """

  customers = await api_client.get_customers()
  await asyncio.gather(*[save_customer(customer) for customer in customers])

  return HttpResponse(status=201, content=f"{len(customers)} customers synced successfully")
