from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx
from huggingface_hub import hf_hub_download
from huggingface_hub.utils import EntryNotFoundError
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


def fetch_model_card_readme(model_id: str) -> FetchedSource | None:
    """The model card's actual markdown source, not the rendered webpage.

    huggingface.co/{model_id} is a React-rendered page — its raw HTML is
    mostly boilerplate around the real content, which defeats the point of
    an "excerpt". README.md in the repo *is* the model card's source text,
    fetched the same trusted way Task 4 already fetches config.json.
    Returns None if the repo has no README.md, so the caller can fall back
    to fetching the page itself as a last resort.
    """
    try:
        cached_path = hf_hub_download(repo_id=model_id, filename="README.md")
    except EntryNotFoundError:
        return None
    text = Path(cached_path).read_text(encoding="utf-8")
    return FetchedSource(
        url=f"https://huggingface.co/{model_id}/blob/main/README.md",
        retrieved_at=datetime.now(timezone.utc),
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        excerpt=text[:500],
    )
