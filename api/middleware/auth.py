"""Async OAuth Bearer token middleware for FastAPI."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Any

import httpx
from fastapi import HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_LOGGER = logging.getLogger(__name__)

YANDEX_OAUTH_INFO_URL = os.getenv(
    "YANDEX_OAUTH_INFO_URL", "https://login.yandex.ru/info"
)
CACHE_EXPIRATION = timedelta(hours=1)
TOKEN_VALIDATION_TIMEOUT = 5.0

# In-memory token cache: token -> {"user_id": str, "expires_at": datetime}
_token_cache: dict[str, dict[str, Any]] = {}

_bearer_scheme = HTTPBearer(auto_error=True)


async def validate_token_with_yandex(token: str) -> tuple[bool, str | None]:
    """Validate Bearer token via Yandex OAuth API.

    Args:
        token: Bearer token string.

    Returns:
        Tuple of (is_valid, user_id).
    """
    try:
        async with httpx.AsyncClient(timeout=TOKEN_VALIDATION_TIMEOUT) as client:
            response = await client.get(
                YANDEX_OAUTH_INFO_URL,
                headers={"Authorization": f"OAuth {token}"},
            )
            if response.status_code == 200:
                return True, response.json().get("id")
            return False, None
    except httpx.HTTPError as exc:
        _LOGGER.error("Token validation HTTP error: %s", exc, exc_info=True)
        return False, None
    except Exception as exc:
        _LOGGER.error(
            "Unexpected error during token validation: %s", exc, exc_info=True
        )
        return False, None


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(_bearer_scheme),
) -> str:
    """FastAPI dependency: validate Bearer token and return user_id.

    Args:
        credentials: HTTP Bearer credentials from the request.

    Returns:
        Yandex user ID string.

    Raises:
        HTTPException: 403 if token is invalid or expired.
    """
    token = credentials.credentials

    # Check token cache
    cached = _token_cache.get(token)
    if cached and datetime.now() < cached["expires_at"]:
        return cached["user_id"]  # type: ignore[return-value]

    # Validate via Yandex API
    is_valid, user_id = await validate_token_with_yandex(token)
    if not is_valid or user_id is None:
        raise HTTPException(status_code=403, detail="Invalid or expired token")

    # Cache the valid token
    _token_cache[token] = {
        "user_id": user_id,
        "expires_at": datetime.now() + CACHE_EXPIRATION,
    }

    return user_id  # type: ignore[return-value]


def get_request_id(request: Request) -> str:
    """Extract X-Request-Id header from Yandex, or generate a fallback.

    Args:
        request: FastAPI Request object.

    Returns:
        Request ID string.
    """
    import uuid

    return request.headers.get("X-Request-Id", str(uuid.uuid4()))
