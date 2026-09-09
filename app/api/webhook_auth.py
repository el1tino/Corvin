"""Token authentication and rate limiting for the generic webhook endpoint.

Build spec: "a rate-limited and token-authenticated webhook". The MVP runs
as a single process (see docker-compose.yml), so an in-memory sliding
window is sufficient; if this is ever scaled to multiple workers, swap the
counter for a shared store (e.g. Redis) without changing the call site.
"""
from __future__ import annotations

import hmac
import time
from collections import deque

from fastapi import Header, HTTPException, status

from ..config import get_settings

_request_log: deque[float] = deque()


def verify_webhook_token(x_webhook_token: str | None = Header(default=None)) -> None:
    settings = get_settings()
    if x_webhook_token is None or not hmac.compare_digest(x_webhook_token, settings.webhook_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing webhook token")


def enforce_rate_limit() -> None:
    settings = get_settings()
    now = time.monotonic()
    window_start = now - 60.0
    while _request_log and _request_log[0] < window_start:
        _request_log.popleft()
    if len(_request_log) >= settings.webhook_rate_limit_per_minute:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Webhook rate limit exceeded; please retry later",
        )
    _request_log.append(now)
