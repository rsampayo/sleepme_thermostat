"""Config flow for SleepMe Thermostat."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    API_URL,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from .sleepme import SleepMeClient
from .sleepme_api import (
    SleepMeAuthError,
    SleepMeConnectionError,
    SleepMeRateLimited,
)

_LOGGER = logging.getLogger(__name__)


class SleepMeThermostatConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SleepMe Thermostat."""

    VERSION = 4

    def __init__(self) -> None:
        self.api_token: str = ""
        self.claimed_devices: list = []
        self._claimed_devices_dict: dict[str, str] = {}
        self._reauth_entry: ConfigEntry | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow handler for this integration."""
        return SleepMeOptionsFlowHandler()

    @staticmethod
    def _schema(api_token: str = "") -> vol.Schema:
        return vol.Schema(
            {
                vol.Required("api_token", default=api_token): str,
            }
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            _LOGGER.debug(
                "User submitted api token (length=%d)",
                len(user_input.get("api_token", "")),
            )
            self.api_token = user_input.get("api_token", "")

            client = SleepMeClient(self.hass, API_URL, self.api_token)

            try:
                self.claimed_devices = await client.get_claimed_devices()
                if not self.claimed_devices:
                    errors["base"] = "no_devices_found"
                else:
                    return await self.async_step_select_device()
            except SleepMeAuthError:
                errors["base"] = "invalid_token"
            except (SleepMeRateLimited, SleepMeConnectionError):
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error fetching claimed devices")
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=self._schema(self.api_token),
            errors=errors,
        )

    async def async_step_select_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 2: select a device from the list of claimed devices."""
        errors: dict[str, str] = {}

        if user_input is not None:
            device_id = user_input["device_id"]
            name = self._claimed_devices_dict[device_id]

            await self.async_set_unique_id(device_id)
            self._abort_if_unique_id_configured()

            client = SleepMeClient(self.hass, API_URL, self.api_token, device_id)

            try:
                device_status = await client.get_device_status()
                return self.async_create_entry(
                    title=f"Dock Pro {name}",
                    data={
                        "api_token": self.api_token,
                        "device_id": device_id,
                        "firmware_version": device_status.get("about", {}).get(
                            "firmware_version"
                        ),
                        "mac_address": device_status.get("about", {}).get(
                            "mac_address"
                        ),
                        "model": device_status.get("about", {}).get("model"),
                        "serial_number": device_status.get("about", {}).get(
                            "serial_number"
                        ),
                    },
                )
            except SleepMeAuthError:
                errors["base"] = "invalid_token"
            except (SleepMeRateLimited, SleepMeConnectionError):
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Error fetching device status")
                errors["base"] = "cannot_fetch_device_info"

        if self.claimed_devices:
            self._claimed_devices_dict = {
                device["id"]: device["name"] for device in self.claimed_devices
            }
        else:
            errors["base"] = "no_devices_found"

        return self.async_show_form(
            step_id="select_device",
            data_schema=vol.Schema(
                {vol.Required("device_id"): vol.In(self._claimed_devices_dict)}
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Reauth triggered by coordinator raising ConfigEntryAuthFailed."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Prompt for a new API token and validate it against the API."""
        errors: dict[str, str] = {}
        assert self._reauth_entry is not None

        if user_input is not None:
            new_token = user_input["api_token"]
            client = SleepMeClient(self.hass, API_URL, new_token)
            try:
                claimed = await client.get_claimed_devices()
                existing_device_id = self._reauth_entry.data["device_id"]
                if not any(d.get("id") == existing_device_id for d in claimed):
                    errors["base"] = "device_not_found_for_token"
                else:
                    return self.async_update_reload_and_abort(
                        self._reauth_entry,
                        data={**self._reauth_entry.data, "api_token": new_token},
                        reason="reauth_successful",
                    )
            except SleepMeAuthError:
                errors["base"] = "invalid_token"
            except (SleepMeRateLimited, SleepMeConnectionError):
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during reauth")
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required("api_token"): str}),
            errors=errors,
        )


class SleepMeOptionsFlowHandler(OptionsFlow):
    """Options flow: poll interval only (Phase 2).

    `self.config_entry` is set automatically by HA's framework — do not assign
    it in __init__ (the attribute is read-only in HA Core 2024.12+).
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show + handle the options form."""
        errors: dict[str, str] = {}

        if user_input is not None:
            value = user_input[CONF_SCAN_INTERVAL]
            if not MIN_SCAN_INTERVAL <= value <= MAX_SCAN_INTERVAL:
                errors[CONF_SCAN_INTERVAL] = "invalid_scan_interval"
            else:
                return self.async_create_entry(title="", data=user_input)

        current = self.config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )
        # NumberSelector intentionally has no min/max bounds — the Python check
        # below is the single source of truth for the allowed range. Bound
        # enforcement at the schema layer would prevent our `invalid_scan_interval`
        # error key from surfacing in the form.
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL, default=current
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        max=86400,
                        step=1,
                        unit_of_measurement="seconds",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
        )
