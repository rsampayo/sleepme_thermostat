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
        self._current_patch_task = None  # Track the ongoing PATCH request task

    async def _perform_request(self, method: str, endpoint: str, params=None, data=None, input_headers=None, retries=3):
        """Handles low-level API requests with retry logic."""
        request_id = f"{method.upper()}-{endpoint}-{int(time.time())}"
        headers = input_headers or {}
        headers["Authorization"] = f"Bearer {self.token}"

        for attempt in range(retries):
            if method.upper() == "PATCH":
                # Check if this PATCH request is still the latest active one
                if self._current_patch_task and self._current_patch_task != asyncio.current_task():
                    _LOGGER.warning(f"[{request_id}] Retry attempt {attempt + 1} for PATCH request to {endpoint} was canceled because a newer PATCH request was initiated.")
                    return {}  # Exit the retry loop since a newer PATCH request exists

                _LOGGER.debug(f"[{request_id}] Checking if ongoing PATCH request needs to be canceled before retry.")
                await self._cancel_previous_patch()

            try:
                _LOGGER.debug(f"[{request_id}] Attempt {attempt + 1} making {method.upper()} request to {self.api_url}/{endpoint}")
                response = await self.client.request(method, f"{self.api_url}/{endpoint}", headers=headers, json=data, params=params)
                response.raise_for_status()
                _LOGGER.debug(f"[{request_id}] Request to {endpoint} completed successfully with status {response.status_code}.")
                return response.json()  # Process and return the JSON response

            except httpx.HTTPStatusError as e:
                # Handle specific HTTP status codes
                if response.status_code == 403:
                    _LOGGER.error(f"[{request_id}] Invalid API token. Received 403 Forbidden for {self.api_url}/{endpoint}.")
                    raise ValueError("invalid_token")
                elif response.status_code == 429:
                    backoff_time = (2 ** attempt) * 30
                    _LOGGER.warning(f"[{request_id}] 429 Too Many Requests. Retrying after {backoff_time} seconds...")
                    await asyncio.sleep(backoff_time)
                elif response.status_code in {500, 502, 503, 504} and method.upper() != "GET":
                    backoff_time = (2 ** attempt) * 10
                    _LOGGER.warning(f"[{request_id}] Server error {response.status_code}. Retrying after {backoff_time} seconds...")
                    await asyncio.sleep(backoff_time)
                else:
                    _LOGGER.error(f"[{request_id}] HTTP error {response.status_code}: {str(e)}")
                    break
            except httpx.TimeoutException:
                _LOGGER.warning(f"[{request_id}] Timeout occurred. Retrying after backoff...")
                await asyncio.sleep((2 ** attempt) * 10)
            except httpx.RequestError as e:
                _LOGGER.error(f"[{request_id}] Request error: {str(e)}")
                break

        _LOGGER.error(f"[{request_id}] API request to {endpoint} failed after {retries} attempts.")
        return {}  # Return an empty dictionary on failure

    async def _cancel_previous_patch(self):
        """Cancel the ongoing PATCH request if a new one is made."""
        if self._current_patch_task:
            if not self._current_patch_task.done():
                _LOGGER.debug("Attempting to cancel the previous PATCH request...")
                self._current_patch_task.cancel()
                try:
                    await self._current_patch_task
                    _LOGGER.warning("Previous PATCH request and its retries were cancelled successfully.")
                except asyncio.CancelledError:
                    _LOGGER.warning("Previous PATCH request and its retries were cancelled successfully (CancelledError).")
                except Exception as e:
                    _LOGGER.error(f"Error while cancelling the PATCH request: {e}")
                finally:
                    _LOGGER.debug("Previous PATCH request cancellation process completed.")
            else:
                _LOGGER.debug("No previous PATCH request to cancel (it is already done).")
        else:
            _LOGGER.debug("No previous PATCH request exists.")

    async def make_request(self, method: str, endpoint: str, params=None, data=None, input_headers=None):
        """Wrapper method to handle rate limiting and calling _perform_request."""
        request_id = f"{method.upper()}-{endpoint}-{int(time.time())}"

        if method.upper() == "PATCH":
            _LOGGER.debug(f"[{request_id}] Initiating PATCH request to {endpoint}. Checking for any ongoing PATCH requests to cancel...")
            await self._cancel_previous_patch()

        async with asyncio.Lock():
            current_time = time.time()

            # Rate limiting logic
            if len(self.request_times) == self.request_times.maxlen and current_time - self.request_times[0] < self.rate_limit_interval:
                if method.upper() == "GET":
                    _LOGGER.warning(f"[{request_id}] Discarding GET request to {endpoint} due to rate limiting.")
                    return {}  # Discard the GET request and return an empty dictionary
                else:
                    wait_time = self.rate_limit_interval - (current_time - self.request_times[0])
                    _LOGGER.debug(f"[{request_id}] Rate limiting: waiting for {wait_time:.2f} seconds before making {method.upper()} request to {endpoint}.")
                    await asyncio.sleep(wait_time)

            # Add the current time to the deque
            self.request_times.append(current_time)

        # Track the PATCH request task for cancellation if needed
        if method.upper() == "PATCH":
            _LOGGER.debug(f"[{request_id}] Starting new PATCH request to {endpoint}.")
            self._current_patch_task = asyncio.create_task(
                self._perform_request(method, endpoint, params=params, data=data, input_headers=input_headers)
            )
            result = await self._current_patch_task
            _LOGGER.debug(f"[{request_id}] PATCH request to {endpoint} completed.")
            return result
        else:
            _LOGGER.debug(f"[{request_id}] Starting {method.upper()} request to {endpoint}.")
            result = await self._perform_request(method, endpoint, params=params, data=data, input_headers=input_headers)
            _LOGGER.debug(f"[{request_id}] {method.upper()} request to {endpoint} completed.")
            return result

    async def close(self):
        """Close the httpx client."""
        _LOGGER.debug("Closing HTTP client...")
        await self.client.aclose()
        _LOGGER.debug("HTTP client closed.")
