from __future__ import annotations

from pydantic import BaseModel


class Evidence(BaseModel):
    field: str
    value: str
    source: str
    detail: str
