"""HTTP transport for the SleepMe developer API.

Responsibilities:
- Authorize requests with bearer token.
- Rate-limit locally (sliding window, concurrency-safe via instance lock).
- Retry on 429 + 5xx with monotonically increasing backoff, honoring Retry-After.
- Surface auth failures (401/403) and connection failures as typed exceptions.

Does NOT:
- Queue requests when the local rate limiter would block. Raises
  SleepMeRateLimited; caller (coordinator, config flow, climate path) decides.
- Manage its own httpx client lifecycle. The client is HA's shared instance,
  obtained via get_async_client(hass).

If the server asks us to wait (Retry-After), we honor that inside api_request.
While that sleep is in progress the local deque is not cleared, so a concurrent
caller can still trip SleepMeRateLimited — which is the desired behavior:
the server is asking us to back off, so we should locally back off too.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Mapping
from email.utils import parsedate_to_datetime
from typing import Any
from weakref import WeakValueDictionary

import httpx
from homeassistant.core import HomeAssistant
from homeassistant.helpers.httpx_client import get_async_client

_LOGGER = logging.getLogger(__name__)

MAX_REQUESTS_PER_MINUTE = 9
RATE_LIMIT_WINDOW = 60  # seconds
# Edge grace: when the deque is at capacity but the oldest entry is within this
# many seconds of expiring, absorb the wait in-call instead of raising. Prevents
# benign timing skew at the window boundary from cascading into UpdateFailed +
# entity-flap when an install sits at the per-account ceiling (e.g. 3 devices
# polling at 20s = 9 req/min exactly).
RATE_LIMIT_EDGE_GRACE = 5.0  # seconds
DEFAULT_RETRIES = 3
BACKOFF_BASE_429 = 30  # seconds
BACKOFF_BASE_5XX = 10  # seconds
BACKOFF_BASE_TIMEOUT = 10  # seconds
BACKOFF_CEILING = (
    600  # seconds (10 min); Retry-After may exceed this and we honor it anyway.
)


class SleepMeAPIError(Exception):
    """Base for typed transport errors."""


class SleepMeAuthError(SleepMeAPIError):
    """401/403 from the API. Coordinator should raise ConfigEntryAuthFailed."""


class SleepMeRateLimited(SleepMeAPIError):
    """Local rate-limiter would have blocked the request. Caller decides retry."""


class SleepMeConnectionError(SleepMeAPIError):
    """Network-level failure (DNS, refused, timeout). Coordinator should raise UpdateFailed."""


class SleepMeAPI:
    """Per-(api_url, token) transport instance.

    The class-level `_instances` cache dedupes SleepMeAPI objects by (api_url,
    token). All SleepMeClient instances using the same token share one deque
    and one lock — so the local rate limiter actually maps to the per-account
    server-side budget instead of multiplying by N config entries.

    `_instances` is a WeakValueDictionary: as soon as the last SleepMeClient
    referencing a given transport is GC'd (e.g. all entries with that token
    are unloaded), the cached entry disappears.
    """

    _instances: WeakValueDictionary[tuple[str, str], SleepMeAPI] = WeakValueDictionary()

    @classmethod
    def get_or_create(
        cls,
        hass: HomeAssistant,
        api_url: str,
        token: str,
        max_requests_per_minute: int = MAX_REQUESTS_PER_MINUTE,
    ) -> SleepMeAPI:
        """Return the shared transport for this (api_url, token) pair."""
        key = (api_url, token)
        existing = cls._instances.get(key)
        if existing is not None:
            return existing
        new = cls(hass, api_url, token, max_requests_per_minute)
        cls._instances[key] = new
        return new

    def __init__(
        self,
        hass: HomeAssistant,
        api_url: str,
        token: str,
        max_requests_per_minute: int = MAX_REQUESTS_PER_MINUTE,
    ) -> None:
        self.api_url = api_url
        self.token = token
        self.client = get_async_client(hass)
        self._request_times: deque[float] = deque(maxlen=max_requests_per_minute)
        self._lock = asyncio.Lock()

    # No close() — the httpx client is HA's shared instance and we must not close it.

    async def api_request(
        self,
        method: str,
        endpoint: str,
        *,
        data: dict | None = None,
        params: Mapping[str, str | int] | None = None,
        retries: int = DEFAULT_RETRIES,
    ) -> Any:
        """Send one request with retry-on-transient-error.

        Raises:
            SleepMeAuthError: on 401/403.
            SleepMeRateLimited: if local rate limiter would block (no queueing).
            SleepMeConnectionError: on network failure or timeout exhaustion.
            httpx.HTTPStatusError: on non-retriable HTTP errors after retries exhausted.
        """
        attempt = 1
        while True:
            await self._enforce_local_rate_limit(method, endpoint)
            try:
                return await self._perform_request(
                    method, endpoint, data=data, params=params
                )
            except httpx.HTTPStatusError as err:
                status = err.response.status_code
                if status in (401, 403):
                    raise SleepMeAuthError(f"{status} from {endpoint}") from err
                if status == 429 and attempt <= retries:
                    backoff = self._compute_backoff(
                        BACKOFF_BASE_429, attempt, err.response
                    )
                    _LOGGER.warning(
                        "429 on %s %s; attempt %d/%d, sleeping %.1fs",
                        method,
                        endpoint,
                        attempt,
                        retries,
                        backoff,
                    )
                    await asyncio.sleep(backoff)
                    attempt += 1
                    continue
                if status in (500, 502, 503, 504) and attempt <= retries:
                    backoff = self._compute_backoff(
                        BACKOFF_BASE_5XX, attempt, err.response
                    )
                    _LOGGER.warning(
                        "HTTP %d on %s %s; attempt %d/%d, sleeping %.1fs",
                        status,
                        method,
                        endpoint,
                        attempt,
                        retries,
                        backoff,
                    )
                    await asyncio.sleep(backoff)
                    attempt += 1
                    continue
                # Non-retriable / out of retries: re-raise.
                raise
            except httpx.TimeoutException as err:
                if attempt > retries:
                    raise SleepMeConnectionError(f"timeout on {endpoint}") from err
                backoff = min(
                    BACKOFF_BASE_TIMEOUT * (2 ** (attempt - 1)), BACKOFF_CEILING
                )
                _LOGGER.warning(
                    "Timeout on %s %s; attempt %d/%d, sleeping %.1fs",
                    method,
                    endpoint,
                    attempt,
                    retries,
                    backoff,
                )
                await asyncio.sleep(backoff)
                attempt += 1
            except httpx.RequestError as err:
                # DNS, connection refused, etc. Not worth retrying in-call;
                # coordinator's next poll will retry.
                raise SleepMeConnectionError(
                    f"request error on {endpoint}: {err}"
                ) from err

    async def _enforce_local_rate_limit(self, method: str, endpoint: str) -> None:
        """Record the request, briefly wait at the window edge, or raise.

        Sliding window: drop entries older than RATE_LIMIT_WINDOW, then check
        capacity. If at capacity but the wait is small (<= RATE_LIMIT_EDGE_GRACE)
        we sleep in-call — multi-device installs sitting at the per-account
        ceiling routinely tip a few ms past the edge, and turning that into an
        ERROR + UpdateFailed every cycle is the worst kind of log noise. Larger
        waits still raise: caller decides.
        """
        async with self._lock:
            now = time.monotonic()
            while (
                self._request_times
                and now - self._request_times[0] >= RATE_LIMIT_WINDOW
            ):
                self._request_times.popleft()

            maxlen = self._request_times.maxlen
            if maxlen is not None and len(self._request_times) >= maxlen:
                wait = RATE_LIMIT_WINDOW - (now - self._request_times[0])
                if wait <= RATE_LIMIT_EDGE_GRACE:
                    _LOGGER.debug(
                        "Local rate-limit edge on %s %s; waiting %.3fs in-call",
                        method,
                        endpoint,
                        wait,
                    )
                    await asyncio.sleep(max(wait, 0.0))
                    now = time.monotonic()
                    while (
                        self._request_times
                        and now - self._request_times[0] >= RATE_LIMIT_WINDOW
                    ):
                        self._request_times.popleft()
                    self._request_times.append(now)
                    return
                _LOGGER.warning(
                    "Local rate limit hit on %s %s; would need %.1fs. Rejecting.",
                    method,
                    endpoint,
                    wait,
                )
                raise SleepMeRateLimited(
                    f"{method} {endpoint}: local rate-limiter at capacity"
                )

            self._request_times.append(now)

    async def _perform_request(
        self,
        method: str,
        endpoint: str,
        *,
        data: dict | None,
        params: Mapping[str, str | int] | None,
    ) -> Any:
        headers = {"Authorization": f"Bearer {self.token}"}
        _LOGGER.debug("%s %s/%s data=%s", method, self.api_url, endpoint, data)
        response = await self.client.request(
            method,
            f"{self.api_url}/{endpoint}",
            headers=headers,
            json=data,
            params=params,
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _compute_backoff(base: int, attempt: int, response: httpx.Response) -> float:
        """Resolve backoff seconds.

        Honors Retry-After (integer seconds or HTTP-date), capped at
        BACKOFF_CEILING to bound worst-case downtime when the server returns
        an extreme value. Falls back to base * 2**(attempt-1), also capped.
        """

        def _cap(v: float) -> float:
            if v > BACKOFF_CEILING:
                _LOGGER.warning(
                    "Capping Retry-After %.0fs to ceiling %ds", v, BACKOFF_CEILING
                )
            return min(v, float(BACKOFF_CEILING))

        ra = response.headers.get("Retry-After")
        if ra:
            try:
                return _cap(float(int(ra)))
            except ValueError:
                try:
                    target = parsedate_to_datetime(ra).timestamp()
                    return _cap(max(0.0, target - time.time()))
                except (TypeError, ValueError):
                    _LOGGER.debug("Unparsable Retry-After: %r", ra)
        return float(min(base * (2 ** (attempt - 1)), BACKOFF_CEILING))
