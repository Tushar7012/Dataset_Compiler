from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel

# (host, path prefix) pairs. Both must match — "github.com" alone would let
# through any repo on GitHub, not just the official ones we trust.
ALLOWED_SOURCES = (
    ("huggingface.co", "/"),
    ("github.com", "/huggingface/transformers"),
    ("github.com", "/huggingface/trl"),
    ("github.com", "/unslothai/unsloth"),
    ("docs.unsloth.ai", "/"),
)


class SourceNotAllowedError(RuntimeError):
    pass


class FetchedSource(BaseModel):
    url: str
    retrieved_at: datetime
    sha256: str
    excerpt: str


def _is_allowed(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return False
    hostname = parsed.hostname or ""
    path = parsed.path or "/"
    for host, prefix in ALLOWED_SOURCES:
        host_matches = hostname == host or hostname.endswith(f".{host}")
        if host_matches and path.startswith(prefix):
            return True
    return False


async def fetch_source(url: str, client: httpx.AsyncClient) -> FetchedSource:
    if not _is_allowed(url):
        raise SourceNotAllowedError(f"{url} is not on the official-sources allowlist")
    response = await client.get(url)
    response.raise_for_status()
    text = response.text
    return FetchedSource(
        url=url,
        retrieved_at=datetime.now(timezone.utc),
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        excerpt=text[:500],
    )


def model_card_url(model_id: str) -> str:
    return f"https://huggingface.co/{model_id}"
