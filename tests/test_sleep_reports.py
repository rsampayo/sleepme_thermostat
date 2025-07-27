import sys
import types
import os
import importlib
import pytest

# Ensure repository root and custom_components are on sys.path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "custom_components"))

# Stub minimal homeassistant modules to satisfy imports
ha = types.ModuleType('homeassistant')
ha.helpers = types.ModuleType('homeassistant.helpers')
ha.helpers.httpx_client = types.ModuleType('homeassistant.helpers.httpx_client')
async def get_async_client(hass):
    class DummyClient:
        async def request(self, method, url, headers=None, json=None, params=None):
            class Response:
                status_code = 200
                def json(self):
                    return {}
                def raise_for_status(self):
                    pass
            return Response()
        async def aclose(self):
            pass
    return DummyClient()
ha.helpers.httpx_client.get_async_client = get_async_client
ha.core = types.ModuleType('homeassistant.core')
ha.core.HomeAssistant = type('HomeAssistant', (), {})

sys.modules['homeassistant'] = ha
sys.modules['homeassistant.helpers'] = ha.helpers
sys.modules['homeassistant.helpers.httpx_client'] = ha.helpers.httpx_client
sys.modules['homeassistant.core'] = ha.core

sleepme_module = importlib.import_module('custom_components.sleepme_thermostat.sleepme')

class DummyAPI:
    def __init__(self, hass, api_url, token, max_requests_per_minute=9):
        self.calls = []
    async def api_request(self, method, endpoint, params=None, data=None, input_headers=None, retries=3):
        self.calls.append((method, endpoint, params))
        return {"reports": [{"sleep_score_percent": 90}]}

sleepme_module.SleepMeAPI = DummyAPI

@pytest.mark.asyncio
async def test_get_sleep_report():
    client = sleepme_module.SleepMeClient(None, 'http://mock', 'token')
    report = await client.get_sleep_report(start_date='2024-01-01', days_back=1)
    assert report['reports'][0]['sleep_score_percent'] == 90
