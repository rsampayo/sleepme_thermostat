import asyncio
import httpx
import logging
import time
from homeassistant.helpers.httpx_client import get_async_client
from homeassistant.core import HomeAssistant
from collections import deque

_LOGGER = logging.getLogger(__name__)

class SleepMeAPI:
    def __init__(self, hass: HomeAssistant, api_url: str, token: str, max_requests_per_minute=9):
        self.api_url = api_url
        self.token = token
        self.client = get_async_client(hass)
        self.request_times = deque(maxlen=max_requests_per_minute)
        self.rate_limit_interval = 60  # seconds

    async def api_request(self, method: str, endpoint: str, params=None, data=None, input_headers=None, retries=3):
        """Handles rate limiting, retries, and calls perform_request."""
        request_id = f"{method.upper()}-{endpoint}-{int(time.time())}"
        _LOGGER.debug(f"[{request_id}] Starting API request with {retries} retries remaining.")

        async with asyncio.Lock():
            current_time = time.time()

            # Rate limiting logic
            if len(self.request_times) == self.request_times.maxlen and current_time - self.request_times[0] < self.rate_limit_interval:
                wait_time = self.rate_limit_interval - (current_time - self.request_times[0])

                if method.upper() == "GET":
                    _LOGGER.warning(f"[{request_id}] Rate limiting active. Discarding GET request to {endpoint} instead of delaying by {wait_time:.2f} seconds.")
                    return {}  # Discard the GET request and return an empty dictionary

                _LOGGER.debug(f"[{request_id}] Rate limiting: waiting for {wait_time:.2f} seconds before making {method.upper()} request to {endpoint}.")
                await asyncio.sleep(wait_time)

            # Add the current time to the deque
            self.request_times.append(current_time)

        # Perform the API request
        try:
            result = await self.perform_request(method, endpoint, params=params, data=data, input_headers=input_headers)
            _LOGGER.debug(f"[{request_id}] API request successful.")
            return result
        except Exception as e:
            _LOGGER.debug(f"[{request_id}] Exception occurred: {e}. Passing to handle_error.")
            return await self.handle_error(e, method, endpoint, params, data, input_headers, retries)

    async def perform_request(self, method: str, endpoint: str, params=None, data=None, input_headers=None):
        """Executes the actual API request."""
        request_id = f"{method.upper()}-{endpoint}-{int(time.time())}"
        headers = input_headers or {}
        headers["Authorization"] = f"Bearer {self.token}"

        _LOGGER.debug(f"[{request_id}] Making {method.upper()} request to {self.api_url}/{endpoint} with params: {params} and data: {data}")
        response = await self.client.request(method, f"{self.api_url}/{endpoint}", headers=headers, json=data, params=params)
        response.raise_for_status()
        _LOGGER.debug(f"[{request_id}] Request to {endpoint} completed successfully with status {response.status_code}.")
        return response.json()  # Process and return the JSON response

    async def handle_error(self, error, method: str, endpoint: str, params=None, data=None, input_headers=None, retries=3):
        """Classifies errors and applies backoff before retrying if necessary."""
        request_id = f"{method.upper()}-{endpoint}-{int(time.time())}"

        if retries <= 0:
            _LOGGER.debug(f"[{request_id}] API request to {endpoint} failed after all retries.")
            return {}  # Return an empty dictionary on failure

        _LOGGER.warning(f"[{request_id}] Handling error: {error}. Retries remaining: {retries}")

        # Determine backoff time based on error type
        if isinstance(error, httpx.HTTPStatusError):
            if error.response.status_code == 403:
                _LOGGER.debug(f"[{request_id}] Invalid API token. Received 403 Forbidden for {self.api_url}/{endpoint}.")
                raise ValueError("invalid_token")
            elif error.response.status_code == 429:
                # Backoff times: 30, 60, 120, 240... seconds for 429 errors
                initial_backoff = 30
                _LOGGER.warning(f"[{request_id}] 429 Too Many Requests. Applying backoff starting at {initial_backoff} seconds.")
            elif error.response.status_code in {500, 502, 503, 504}:
                # Backoff times: 10, 20, 40, 80... seconds for server errors
                initial_backoff = 10
                _LOGGER.warning(f"[{request_id}] Server error {error.response.status_code}. Applying backoff starting at {initial_backoff} seconds.")
            else:
                _LOGGER.debug(f"[{request_id}] HTTP error {error.response.status_code}. No retry configured.")
                raise ValueError("cannot_connect")
        elif isinstance(error, httpx.TimeoutException):
            # Backoff times: 10, 20, 40, 80... seconds for timeouts
            initial_backoff = 10
            _LOGGER.warning(f"[{request_id}] Timeout occurred. Applying backoff starting at {initial_backoff} seconds.")
        elif isinstance(error, httpx.RequestError):
            _LOGGER.debug(f"[{request_id}] Request error: {error}. Cannot connect.")
            raise ValueError("cannot_connect")

        backoff_time = initial_backoff * (2 ** (retries - 1))
        _LOGGER.warning(f"[{request_id}] Retrying after {backoff_time} seconds. Retries left: {retries-1}")

        await asyncio.sleep(backoff_time)

        # Retry the API request with one less retry
        return await self.api_request(method, endpoint, params=params, data=data, input_headers=input_headers, retries=retries-1)

    async def close(self):
        """Close the httpx client."""
        _LOGGER.debug("Closing HTTP client...")
        await self.client.aclose()
        _LOGGER.debug("HTTP client closed.")
