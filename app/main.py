from fastapi import FastAPI

from .lexoffice.dependencies import ApiClient

app = FastAPI()

api_client = ApiClient()

@app.get("/")
async def read_root():
  return {"Hello": "World"}

@app.get("/customers")
async def read_customers():
  return await api_client.get_customers()
