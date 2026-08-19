from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel


class ProviderHealth(BaseModel):
    healthy: bool
    detail: str


class GenerationRequest(BaseModel):
    messages: list[dict]
    temperature: float = 0.7
    max_tokens: int | None = None
    response_format: dict | None = None


class GenerationResponse(BaseModel):
    content: str
    raw: dict


class ProviderProfile(BaseModel):
    name: str
    base_url: str
    model: str
    credential_reference: str | None = None
    timeout_seconds: float = 30.0
    max_concurrency: int = 4
    structured_output_supported: bool = False


class ChatProvider(Protocol):
    async def health(self) -> ProviderHealth: ...
    async def generate(self, request: GenerationRequest) -> GenerationResponse: ...
