from __future__ import annotations

from pathlib import Path

import httpx
from docling_core.types.doc.document import DoclingDocument

from tuneforge.ingestion.documents import CorruptDocumentError, EncryptedDocumentError

_RETRYABLE_STATUS_CODES = {502, 503, 504}
_MAX_RETRIES = 3
_DEFAULT_TIMEOUT_SECONDS = 60.0


class RemoteParsingUnavailableError(RuntimeError):
    pass


def convert_document_remote(
    path: Path,
    *,
    base_url: str,
    token: str | None = None,
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    client: httpx.Client | None = None,
) -> DoclingDocument:
    """Sends the file's raw bytes to a remote docling-parsing service (the DGX
    GPU service) and returns the resulting DoclingDocument.

    Raises EncryptedDocumentError/CorruptDocumentError for content problems —
    same vocabulary as convert_document, callers can't tell local from remote
    apart from the exception type. Raises RemoteParsingUnavailableError if the
    service can't be reached at all after retries; the caller (not this
    function) decides whether to fall back to local parsing.
    """
    headers = {"Content-Type": "application/octet-stream", "X-Document-Filename": path.name}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = path.read_bytes()
    url = f"{base_url.rstrip('/')}/convert"

    owns_client = client is None
    client = client or httpx.Client(timeout=timeout_seconds)
    try:
        attempt = 0
        while True:
            attempt += 1
            try:
                response = client.post(url, content=body, headers=headers, timeout=timeout_seconds)
            except httpx.HTTPError as exc:
                if attempt > _MAX_RETRIES:
                    raise RemoteParsingUnavailableError(
                        f"{base_url}: request failed after {attempt} attempts: {exc}"
                    ) from exc
                continue

            if response.status_code in _RETRYABLE_STATUS_CODES:
                if attempt > _MAX_RETRIES:
                    raise RemoteParsingUnavailableError(
                        f"{base_url}: status {response.status_code} after {attempt} attempts"
                    )
                continue

            if response.status_code == 422:
                detail = response.json()
                if detail.get("error") == "encrypted":
                    raise EncryptedDocumentError(f"{path.name}: is password-protected or encrypted")
                raise CorruptDocumentError(f"{path.name}: could not be parsed — {detail.get('detail', '')}")

            if response.status_code != 200:
                raise RemoteParsingUnavailableError(f"{base_url}: unexpected status {response.status_code}")

            return DoclingDocument.model_validate(response.json())
    finally:
        if owns_client:
            client.close()
