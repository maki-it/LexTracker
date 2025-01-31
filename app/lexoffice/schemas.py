# Pydantic Models for lexoffice API
from __future__ import annotations
from typing import List, Optional

from pydantic import BaseModel, Field, UUID4


class Customer(BaseModel):
  id: UUID4 = Field(description="Unique identifier for the customer")
  organization_id: UUID4 = Field(description="Unique identifier for the organization")


