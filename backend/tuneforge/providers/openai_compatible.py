from __future__ import annotations

import logging
import uuid

import httpx

from tuneforge.providers.protocol import (
    GenerationRequest,
    GenerationResponse,
    ProviderHealth,
    ProviderProfile,
    RunConsent,
)
from tuneforge.security.credentials import get_api_key

logger = logging.getLogger("tuneforge.providers")

_RETRYABLE_STATUS_CODES = {429, 502, 503, 504}
_MAX_RETRIES = 3


class ProviderAuthError(RuntimeError):
    pass


class ProviderResponseError(RuntimeError):
    pass


class RemoteConsentRequiredError(RuntimeError):
    pass


class OpenAICompatibleProvider:
    def __init__(self, profile: ProviderProfile, client: httpx.AsyncClient):
        self.profile = profile
        self._client = client

    def _headers(self, request_id: str) -> dict[str, str]:
        headers = {"X-Request-ID": request_id}
        if self.profile.credential_reference:
            headers["Authorization"] = f"Bearer {get_api_key(self.profile.credential_reference)}"
        return headers

    async def health(self) -> ProviderHealth:
        request_id = uuid.uuid4().hex
        logger.info("provider health check request_id=%s provider=%s", request_id, self.profile.name)
        try:
            response = await self._client.get("/v1/models", headers=self._headers(request_id))
        except httpx.HTTPError as exc:
            return ProviderHealth(healthy=False, detail=f"request failed: {type(exc).__name__}")
        if response.status_code == 200:
            return ProviderHealth(healthy=True, detail="ok")
        return ProviderHealth(healthy=False, detail=f"status {response.status_code}")

    async def generate(
        self, request: GenerationRequest, consent: RunConsent | None = None
    ) -> GenerationResponse:
        if self.profile.endpoint_scope == "remote" and consent is None:
            raise RemoteConsentRequiredError(
                f"provider {self.profile.name!r} is remote; a run-specific consent "
                "record is required before sending anything to it"
            )

        request_id = uuid.uuid4().hex
        payload: dict = {
            "model": self.profile.model,
            "messages": request.messages,
            "temperature": request.temperature,
        }
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        if request.response_format is not None:
            payload["response_format"] = request.response_format

        attempt = 0
        while True:
            attempt += 1
            logger.info(
                "provider generate request_id=%s provider=%s attempt=%s",
                request_id,
                self.profile.name,
                attempt,
            )
            try:
                response = await self._client.post(
                    "/v1/chat/completions", json=payload, headers=self._headers(request_id)
                )
            except httpx.TimeoutException:
                if attempt > _MAX_RETRIES:
                    raise ProviderResponseError(f"request_id={request_id}: timed out after {attempt} attempts")
                continue

            if response.status_code in (401, 403):
                raise ProviderAuthError(f"request_id={request_id}: authentication rejected")

            if response.status_code in _RETRYABLE_STATUS_CODES:
                if attempt > _MAX_RETRIES:
                    raise ProviderResponseError(
                        f"request_id={request_id}: status {response.status_code} after {attempt} attempts"
                    )
                continue

            if response.status_code != 200:
                raise ProviderResponseError(f"request_id={request_id}: status {response.status_code}")

            data = response.json()
            try:
                content = data["choices"][0]["message"]["content"]
            except (KeyError, IndexError) as exc:
                raise ProviderResponseError(f"request_id={request_id}: malformed response") from exc
            return GenerationResponse(content=content, raw=data)
