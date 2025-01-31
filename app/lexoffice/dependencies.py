from typing import Any, AsyncGenerator

from httpx import AsyncClient

from .config import get_config


class ApiClient:
  def __init__(self):
    self.config = get_config()
    self.client = AsyncClient(
        base_url=self.config.url,
        headers={
          'Authorization': f'Bearer {self.config.token}',
          'Accept': 'application/json',
          'Content-Type': 'application/json'
        }
    )

  async def get(self, endpoint: str, params=None) -> Any:
    """
    Makes a GET request to the Lexoffice API
    :param params:
    :param endpoint: str
    :return: Any
    """

    if params is None:
      params = {}

    response = await self.client.get(endpoint, params=params)
    response.raise_for_status()
    return response.json()


  async def get_customers(self) -> Any:
    """
    Returns a list of contacts from Lexoffice API
    :return: Any
    """

    return await self.get('/contacts', params={'customer': True, 'vendor': False})

