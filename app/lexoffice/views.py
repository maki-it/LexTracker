import asyncio

from pydantic import UUID4
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.utils.translation import ngettext

from .utils import api_client, save_customer

# Create your views here.

@login_required
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


@login_required
async def sync_customers(request):
  """
  Sync customers from Lexoffice API to local database
  :param request:
  :return:
  """

  customers = await api_client.get_customers()
  await asyncio.gather(*[save_customer(customer) for customer in customers])

  return HttpResponse(status=201, content=ngettext(
    '%d Customer synced',
    '%d Customers synced',
    len(customers),
  ) % len(customers))
