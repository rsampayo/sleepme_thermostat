import asyncio
import httpx
import logging
import time
from collections import deque

_LOGGER = logging.getLogger(__name__)

class SleepMeAPI:
    def __init__(self, api_url: str, token: str, max_requests_per_minute=9):
        self.api_url = api_url
        self.token = token
        self.client = httpx.AsyncClient()
        self.request_times = deque(maxlen=max_requests_per_minute)
        self.rate_limit_interval = 60  # seconds

    async def api_request(self, method: str, endpoint: str, params=None, data=None, input_headers=None, retries=1):
        """Handles rate limiting, retries, and calls perform_request."""
        request_id = f"{method.upper()}-{endpoint}-{int(time.time())}"

        async with asyncio.Lock():
            current_time = time.time()

            # Rate limiting logic
            if len(self.request_times) == self.request_times.maxlen and current_time - self.request_times[0] < self.rate_limit_interval:
                wait_time = self.rate_limit_interval - (current_time - self.request_times[0])
                _LOGGER.debug(f"[{request_id}] Rate limiting: waiting for {wait_time:.2f} seconds before making {method.upper()} request to {endpoint}.")
                await asyncio.sleep(wait_time)

            # Add the current time to the deque
            self.request_times.append(current_time)

        # Perform the API request
        try:
            result = await self.perform_request(method, endpoint, params=params, data=data, input_headers=input_headers)
            return result
        except Exception as e:
            return await self.handle_error(e, method, endpoint, params, data, input_headers, retries)

    async def perform_request(self, method: str, endpoint: str, params=None, data=None, input_headers=None):
        """Executes the actual API request."""
        request_id = f"{method.upper()}-{endpoint}-{int(time.time())}"
        headers = input_headers or {}
        headers["Authorization"] = f"Bearer {self.token}"

        _LOGGER.debug(f"[{request_id}] Making {method.upper()} request to {self.api_url}/{endpoint}")
        response = await self.client.request(method, f"{self.api_url}/{endpoint}", headers=headers, json=data, params=params)
        response.raise_for_status()
        _LOGGER.debug(f"[{request_id}] Request to {endpoint} completed successfully with status {response.status_code}.")
        return response.json()  # Process and return the JSON response

    async def handle_error(self, error, method: str, endpoint: str, params=None, data=None, input_headers=None, retries=3):
        """Classifies errors and applies backoff before retrying if necessary."""
        request_id = f"{method.upper()}-{endpoint}-{int(time.time())}"

        if retries <= 0:
            _LOGGER.error(f"[{request_id}] API request to {endpoint} failed after all retries.")
            return {}  # Return an empty dictionary on failure

        _LOGGER.error(f"[{request_id}] Error during API request: {error}. Retries remaining: {retries}")

        # Backoff and retry based on the error type
        if isinstance(error, httpx.HTTPStatusError):
            if error.response.status_code == 403:
                _LOGGER.error(f"[{request_id}] Invalid API token. Received 403 Forbidden for {self.api_url}/{endpoint}.")
                raise ValueError("invalid_token")
            elif error.response.status_code == 429:
                backoff_time = 30 * (2 ** (3 - retries))
                _LOGGER.warning(f"[{request_id}] 429 Too Many Requests. Retrying after {backoff_time} seconds...")
                await asyncio.sleep(backoff_time)
            elif error.response.status_code in {500, 502, 503, 504}:
                backoff_time = 10 * (2 ** (3 - retries))
                _LOGGER.warning(f"[{request_id}] Server error {error.response.status_code}. Retrying after {backoff_time} seconds...")
                await asyncio.sleep(backoff_time)
        elif isinstance(error, httpx.TimeoutException):
            backoff_time = 10 * (2 ** (3 - retries))
            _LOGGER.warning(f"[{request_id}] Timeout occurred. Retrying after {backoff_time} seconds...")
            await asyncio.sleep(backoff_time)
        elif isinstance(error, httpx.RequestError):
            _LOGGER.error(f"[{request_id}] Request error: {error}")
            return {}  # If it's a generic request error, do not retry

        # Retry the API request
        return await self.api_request(method, endpoint, params=params, data=data, input_headers=input_headers, retries=retries-1)

    async def close(self):
        """Close the httpx client."""
        _LOGGER.debug("Closing HTTP client...")
        await self.client.aclose()
        _LOGGER.debug("HTTP client closed.")
