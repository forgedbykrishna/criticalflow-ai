from __future__ import annotations

import hmac

from fastapi import Header, HTTPException

from config.settings import get_settings


def require_api_key(x_api_key: str | None = Header(default=None),
                    authorization: str | None = Header(default=None)) -> None:
    """No-op unless API_KEY is configured. Accepts `X-API-Key: <key>` or `Authorization: Bearer <key>` (M2 uses Bearer)."""
    expected = get_settings().api_key
    if not expected:
        return
    token = x_api_key
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if not (token and hmac.compare_digest(token, expected)):
        raise HTTPException(status_code=401, detail="Invalid or missing API key (X-API-Key or Authorization: Bearer)")
