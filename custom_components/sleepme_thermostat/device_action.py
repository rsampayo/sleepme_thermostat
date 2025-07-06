"""Provide device actions for SleepMe Thermostat."""

from __future__ import annotations

from homeassistant.components.climate import DOMAIN as CLIMATE_DOMAIN, SERVICE_SET_TEMPERATURE
from homeassistant.const import ATTR_ENTITY_ID, ATTR_TEMPERATURE
from homeassistant.core import HomeAssistant, callback, Context
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.typing import ConfigType, TemplateVarsType
import voluptuous as vol

from .const import DOMAIN

ACTION_TYPE_SET_TEMPERATURE = "set_temperature"

ACTION_SCHEMA = vol.Schema(
    {
        vol.Required("type"): ACTION_TYPE_SET_TEMPERATURE,
        vol.Required(ATTR_ENTITY_ID): str,
        vol.Required(ATTR_TEMPERATURE): vol.Coerce(float),
    }
)


async def async_get_actions(hass: HomeAssistant, device_id: str) -> list[dict]:
    """Return device actions for SleepMe Thermostat."""
    registry = er.async_get(hass)
    actions: list[dict] = []
    for entry in registry.entities.values():
        if (
            entry.domain == CLIMATE_DOMAIN
            and entry.device_id == device_id
            and entry.platform == DOMAIN
        ):
            actions.append(
                {
                    "domain": DOMAIN,
                    "type": ACTION_TYPE_SET_TEMPERATURE,
                    "device_id": device_id,
                    "entity_id": entry.entity_id,
                }
            )
    return actions


async def async_call_action_from_config(
    hass: HomeAssistant,
    config: ConfigType,
    variables: TemplateVarsType,
    context: Context | None,
) -> None:
    """Execute the specified action."""
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {
            ATTR_ENTITY_ID: config[ATTR_ENTITY_ID],
            ATTR_TEMPERATURE: config[ATTR_TEMPERATURE],
        },
        blocking=True,
        context=context,
    )


@callback
def async_get_action_capabilities(
    hass: HomeAssistant, config: ConfigType
) -> vol.Schema:
    """Return action capabilities."""
    return vol.Schema({vol.Required(ATTR_TEMPERATURE): vol.Coerce(float)})
