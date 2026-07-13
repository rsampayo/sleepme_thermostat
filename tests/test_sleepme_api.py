"""Transport-layer tests: backoff, Retry-After, rate-limit-raises."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from custom_components.sleepme_thermostat.sleepme_api import (
    BACKOFF_BASE_429,
    MAX_REQUESTS_PER_MINUTE,
    RATE_LIMIT_EDGE_GRACE,
    RATE_LIMIT_WINDOW,
    SleepMeAPI,
    SleepMeAuthError,
    SleepMeRateLimited,
)
from homeassistant.core import HomeAssistant


@pytest.fixture
def api(hass: HomeAssistant) -> SleepMeAPI:
    """Return a SleepMeAPI instance with a mocked httpx client."""
    inst = SleepMeAPI(hass, "https://api.test/v1", "tok")
    inst.client = MagicMock()
    inst.client.request = AsyncMock()
    return inst


def _http_response(status: int, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(
        status,
        headers=headers or {},
        request=httpx.Request("GET", "https://api.test/v1/devices"),
    )


async def test_backoff_progression_monotonically_increases(
    api: SleepMeAPI,
) -> None:
    """429 with no Retry-After: backoff is 30, 60, 120 across three attempts."""
    responses = [
        _http_response(429),
        _http_response(429),
        _http_response(429),
        _http_response(200),
    ]
    api.client.request.side_effect = [
        (
            httpx.HTTPStatusError("429", request=r.request, response=r)
            if r.status_code == 429
            else r
        )
        for r in responses
    ]
    # Last response needs raise_for_status to be a no-op and json() to return something.
    # Easier path: short-circuit via mock the last call to return a real 200.
    final_ok = MagicMock()
    final_ok.raise_for_status = MagicMock()
    final_ok.json = MagicMock(return_value={"ok": True})
    api.client.request.side_effect = [
        httpx.HTTPStatusError(
            "429", request=responses[0].request, response=responses[0]
        ),
        httpx.HTTPStatusError(
            "429", request=responses[1].request, response=responses[1]
        ),
        httpx.HTTPStatusError(
            "429", request=responses[2].request, response=responses[2]
        ),
        final_ok,
    ]

    with patch(
        "custom_components.sleepme_thermostat.sleepme_api.asyncio.sleep",
        new_callable=AsyncMock,
    ) as mock_sleep:
        result = await api.api_request("GET", "devices", retries=3)

    assert result == {"ok": True}
    waited = [c.args[0] for c in mock_sleep.call_args_list]
    assert waited == [
        BACKOFF_BASE_429 * 1,  # 30
        BACKOFF_BASE_429 * 2,  # 60
        BACKOFF_BASE_429 * 4,  # 120
    ]


async def test_honors_retry_after_integer(api: SleepMeAPI) -> None:
    """Retry-After: 7 overrides the computed backoff."""
    final_ok = MagicMock()
    final_ok.raise_for_status = MagicMock()
    final_ok.json = MagicMock(return_value={"ok": True})
    resp_429 = _http_response(429, headers={"Retry-After": "7"})
    api.client.request.side_effect = [
        httpx.HTTPStatusError("429", request=resp_429.request, response=resp_429),
        final_ok,
    ]

    with patch(
        "custom_components.sleepme_thermostat.sleepme_api.asyncio.sleep",
        new_callable=AsyncMock,
    ) as mock_sleep:
        await api.api_request("GET", "devices", retries=3)

    assert mock_sleep.await_args_list[0].args[0] == 7.0


async def test_get_under_rate_limit_raises(api: SleepMeAPI) -> None:
    """Filling the deque manually triggers SleepMeRateLimited on next call."""
    now = time.monotonic()
    for _ in range(MAX_REQUESTS_PER_MINUTE):
        api._request_times.append(now)

    with pytest.raises(SleepMeRateLimited):
        await api.api_request("GET", "devices", retries=0)


async def test_window_edge_waits_briefly_instead_of_raising(
    api: SleepMeAPI,
) -> None:
    """Deque at capacity but oldest within RATE_LIMIT_EDGE_GRACE: sleep, proceed.

    Models the steady-state for a 3-device install at 20s polling: cumulative
    9 req/min sits exactly at the per-account ceiling, so the next call lands
    a few ms past the window edge. v4.1.1 absorbs that in-call.
    """
    # Oldest entry is 59s old -> wait would be ~1s, within the 5s grace.
    edge_age = RATE_LIMIT_WINDOW - 1.0
    base = time.monotonic() - edge_age
    for _ in range(MAX_REQUESTS_PER_MINUTE):
        api._request_times.append(base)

    final_ok = MagicMock()
    final_ok.raise_for_status = MagicMock()
    final_ok.json = MagicMock(return_value={"ok": True})
    api.client.request.return_value = final_ok

    with patch(
        "custom_components.sleepme_thermostat.sleepme_api.asyncio.sleep",
        new_callable=AsyncMock,
    ) as mock_sleep:
        result = await api.api_request("GET", "devices", retries=0)

    assert result == {"ok": True}
    assert mock_sleep.await_count == 1
    waited = mock_sleep.await_args_list[0].args[0]
    assert 0.0 <= waited <= RATE_LIMIT_EDGE_GRACE


async def test_wait_above_grace_still_raises(api: SleepMeAPI) -> None:
    """Deque at capacity with oldest well inside window still raises."""
    # Oldest entry is 30s old -> wait ~30s, far above the grace.
    base = time.monotonic() - 30.0
    for _ in range(MAX_REQUESTS_PER_MINUTE):
        api._request_times.append(base)

    with pytest.raises(SleepMeRateLimited):
        await api.api_request("GET", "devices", retries=0)


async def test_401_raises_auth_error_immediately(api: SleepMeAPI) -> None:
    """401 is non-retriable; no sleeps; SleepMeAuthError raised."""
    resp = _http_response(401)
    api.client.request.side_effect = httpx.HTTPStatusError(
        "401", request=resp.request, response=resp
    )

    with patch(
        "custom_components.sleepme_thermostat.sleepme_api.asyncio.sleep",
        new_callable=AsyncMock,
    ) as mock_sleep:
        with pytest.raises(SleepMeAuthError):
            await api.api_request("GET", "devices", retries=3)

    assert mock_sleep.await_count == 0


async def test_query_parameters_are_passed_to_httpx(api: SleepMeAPI) -> None:
    """The transport passes sleep-report query parameters separately from URLs."""
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json = MagicMock(return_value={"reports": []})
    api.client.request.return_value = response

    params = {
        "start_date": "2026-07-13",
        "days_back": 6,
        "time_zone": "Europe/Budapest",
    }
    await api.api_request("GET", "sleep-reports", params=params, retries=0)

    assert api.client.request.await_args.kwargs["params"] == params


async def test_compute_backoff_falls_back_when_no_retry_after() -> None:
    """Static computation: base * 2**(attempt-1)."""
    resp = _http_response(429)
    assert SleepMeAPI._compute_backoff(30, 1, resp) == 30
    assert SleepMeAPI._compute_backoff(30, 2, resp) == 60
    assert SleepMeAPI._compute_backoff(30, 3, resp) == 120


async def test_compute_backoff_caps_at_ceiling() -> None:
    """Backoff cannot exceed BACKOFF_CEILING without a Retry-After."""
    resp = _http_response(429)
    # 30 * 2**10 = 30720, which should clamp to BACKOFF_CEILING (600).
    assert SleepMeAPI._compute_backoff(30, 11, resp) == 600


async def test_compute_backoff_caps_huge_retry_after(hass: HomeAssistant) -> None:
    """Server Retry-After is bounded by BACKOFF_CEILING (no 24h parking)."""
    resp = _http_response(429, headers={"Retry-After": "86400"})  # 1 day
    assert SleepMeAPI._compute_backoff(30, 1, resp) == 600


async def test_get_or_create_returns_shared_instance(hass: HomeAssistant) -> None:
    """Same (api_url, token) returns the same SleepMeAPI; different token does not."""
    a = SleepMeAPI.get_or_create(hass, "https://api.test/v1", "token-A")
    b = SleepMeAPI.get_or_create(hass, "https://api.test/v1", "token-A")
    c = SleepMeAPI.get_or_create(hass, "https://api.test/v1", "token-B")
    assert a is b
    assert a is not c


# ---- Hypothesis property tests ---------------------------------------------

from hypothesis import given  # noqa: E402
from hypothesis import strategies as st  # noqa: E402


@given(
    retry_after=st.text(
        alphabet=st.characters(min_codepoint=32, max_codepoint=126),
        max_size=64,
    )
)
def test_compute_backoff_handles_arbitrary_retry_after(retry_after: str) -> None:
    """No printable-ASCII Retry-After string crashes _compute_backoff."""
    resp = httpx.Response(
        429,
        headers={"Retry-After": retry_after},
        request=httpx.Request("GET", "https://x"),
    )
    result = SleepMeAPI._compute_backoff(30, 1, resp)
    assert isinstance(result, float)
    assert result >= 0


@given(attempt=st.integers(min_value=1, max_value=20))
def test_compute_backoff_no_retry_after_is_monotonic(attempt: int) -> None:
    """Without Retry-After, backoff is non-decreasing across attempts."""
    resp = httpx.Response(429, request=httpx.Request("GET", "https://x"))
    prev = SleepMeAPI._compute_backoff(30, max(1, attempt - 1), resp)
    curr = SleepMeAPI._compute_backoff(30, attempt, resp)
    assert curr >= prev
