from __future__ import annotations

import logging
from typing import Callable

from tuneforge.security.credentials import resolved_secrets

_extra_tokens: list[Callable[[], str | None]] = []
_installed = False


def register_redaction_token(get_token: Callable[[], str | None]) -> None:
    """Register an extra secret getter (e.g. a live session token) to strip from logs.

    Evaluated fresh on every log record, so the getter should read live state
    (an attribute, an env var) rather than capture a value at registration time.
    """
    _extra_tokens.append(get_token)


def install_log_redaction() -> None:
    """Strip every credential ever resolved via get_api_key, plus any registered
    extra tokens, from every log record in this process.

    A logging.Filter attached to one logger only runs for records created
    through that exact logger — it does not re-run for ancestors during
    propagation, and uvicorn's own loggers set propagate=False anyway.
    Wrapping the record factory instead catches every record regardless of
    which logger emitted it.

    Process-local: the generation worker runs as a separate OS process
    (multiprocessing's "spawn" context re-imports everything fresh), so
    installing this in the main server process does not reach it — the
    worker entry point must call this again itself.
    """
    global _installed
    if _installed:
        return
    _installed = True
    original_factory = logging.getLogRecordFactory()

    def factory(*args, **kwargs):
        record = original_factory(*args, **kwargs)
        message = record.getMessage()
        redacted = message
        tokens = [*resolved_secrets(), *(get_token() for get_token in _extra_tokens)]
        for token in tokens:
            if token and token in redacted:
                redacted = redacted.replace(token, "***REDACTED***")
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return record

    logging.setLogRecordFactory(factory)
