"""MondayClient — thin sync httpx wrapper around the monday.com GraphQL endpoint.

Responsibilities:
- Build the POST request with the right headers (no Bearer prefix).
- Surface typed exceptions via `mondo.api.errors.from_response`.
- Retry retryable errors with bounded attempts + jittered backoff, honoring
  monday's `retry_in_seconds` extension when present.
- Register the token for redaction in the logging pipeline.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import Any

import httpx
from loguru import logger

from mondo.api.errors import (
    AuthError,
    MondoError,
    NetworkError,
    NotFoundError,
    RetryableError,
    ServiceError,
    from_response,
)
from mondo.logging_ import register_secret
from mondo.version import __version__

DEFAULT_ENDPOINT = "https://api.monday.com/v2"
DEFAULT_TIMEOUT = 60.0
DEFAULT_MAX_RETRIES = 4

SleepFn = Callable[[float], None]


def _default_backoff(attempt: int, retry_after: float | None) -> float:
    """Backoff delay. Honor monday's `retry_in_seconds` when present; otherwise
    use exponential with jitter, capped at 60s."""
    if retry_after is not None:
        return max(0.0, float(retry_after))
    base: float = min(60.0, 2.0 ** (attempt - 1))
    return base + random.uniform(0.0, min(1.0, base / 4))


class MondayClient:
    """Synchronous monday.com GraphQL client."""

    def __init__(
        self,
        *,
        token: str,
        api_version: str,
        endpoint: str = DEFAULT_ENDPOINT,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_sleep: SleepFn = time.sleep,
        http_client: httpx.Client | None = None,
    ) -> None:
        register_secret(token)
        self._token = token
        self._api_version = api_version
        self._endpoint = endpoint
        self._max_retries = max(1, max_retries)
        self._sleep = retry_sleep
        self._client = http_client or httpx.Client(timeout=timeout)
        self._owns_client = http_client is None

    @property
    def api_version(self) -> str:
        return self._api_version

    @property
    def endpoint(self) -> str:
        return self._endpoint

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": self._token,
            "API-Version": self._api_version,
            "Content-Type": "application/json",
            "User-Agent": f"mondo/{__version__}",
        }

    def execute(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """POST the query, return the parsed response envelope, raise on error.

        Retries retryable errors up to `max_retries` times with backoff.
        """
        body = {"query": query, "variables": variables or {}}
        attempt = 0
        last_exc: MondoError | None = None

        while attempt < self._max_retries:
            attempt += 1
            try:
                response = self._client.post(self._endpoint, json=body, headers=self._headers())
            except httpx.TimeoutException as e:
                last_exc = NetworkError(f"request timed out: {e}")
                logger.warning(f"attempt {attempt}: timeout — {e}")
            except httpx.TransportError as e:
                last_exc = NetworkError(f"transport error: {e}")
                logger.warning(f"attempt {attempt}: transport error — {e}")
            else:
                exc = _classify_response(response)
                if exc is None:
                    parsed: dict[str, Any] = response.json()
                    return parsed
                last_exc = exc

            if not isinstance(last_exc, RetryableError) and not isinstance(last_exc, NetworkError):
                raise last_exc

            if attempt >= self._max_retries:
                break

            retry_after = getattr(last_exc, "retry_in_seconds", None)
            delay = _default_backoff(attempt, retry_after)
            logger.info(
                f"retryable error on attempt {attempt}/{self._max_retries}: "
                f"{type(last_exc).__name__} — sleeping {delay:.2f}s"
            )
            self._sleep(delay)

        assert last_exc is not None
        raise last_exc

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> MondayClient:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()


def _classify_response(response: httpx.Response) -> MondoError | None:
    """Turn an httpx response into an exception, or None on success."""
    status = response.status_code

    # HTTP-layer errors.
    if status == 401:
        return AuthError("unauthorized — check your API token")
    if status == 403:
        return AuthError("forbidden — token lacks the required scope")
    if status == 404:
        return NotFoundError("endpoint or resource not found")
    if status >= 500:
        return ServiceError(f"monday returned HTTP {status}")

    # GraphQL-layer errors.
    try:
        parsed = response.json()
    except ValueError:
        return ServiceError(f"invalid JSON response (HTTP {status})")

    return from_response(parsed)
