"""The Auto Aqua Smart Doser integration."""

from __future__ import annotations

import logging
from pathlib import Path

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AutoAquaApi
from .const import (
    CONF_DEVICE_ID,
    DOMAIN,
    DOSE_MAX_ML,
    DOSE_MIN_ML,
    PUMP_COUNT,
)
from .coordinator import AutoAquaDoserCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.NUMBER, Platform.BUTTON]

# Service schema for autoaqua_doser.dose
SERVICE_DOSE = "dose"
ATTR_DEVICE_ID = "device_id"
ATTR_PUMP = "pump"
ATTR_ML = "ml"

SERVICE_DOSE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): str,
        vol.Required(ATTR_PUMP): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=PUMP_COUNT)
        ),
        vol.Required(ATTR_ML): vol.All(
            vol.Coerce(int), vol.Range(min=DOSE_MIN_ML, max=DOSE_MAX_ML)
        ),
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Auto Aqua Smart Doser from a config entry."""
    session = async_get_clientsession(hass, verify_ssl=False)
    api = AutoAquaApi(
        email=entry.data[CONF_EMAIL],
        password=entry.data[CONF_PASSWORD],
        session=session,
    )

    # Authenticate
    await api.authenticate()

    # Create coordinator and do initial data fetch
    coordinator = AutoAquaDoserCoordinator(
        hass=hass,
        api=api,
        device_id=entry.data[CONF_DEVICE_ID],
    )
    await coordinator.async_config_entry_first_refresh()

    # Store coordinator for platforms to access
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Set up entity platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register the dose service (once, shared across all config entries)
    if not hass.services.has_service(DOMAIN, SERVICE_DOSE):
        async def handle_dose(call: ServiceCall) -> None:
            """Handle the autoaqua_doser.dose service call."""
            target_device_id = call.data[ATTR_DEVICE_ID]
            pump = call.data[ATTR_PUMP]
            ml = call.data[ATTR_ML]

            # Find the coordinator for this device
            coord: AutoAquaDoserCoordinator | None = None
            for eid, c in hass.data.get(DOMAIN, {}).items():
                if isinstance(c, AutoAquaDoserCoordinator) and c.device_id == target_device_id:
                    coord = c
                    break

            if coord is None:
                _LOGGER.error(
                    "No configured doser found with device_id %s", target_device_id
                )
                return

            await coord.async_dose(pump, ml)

        hass.services.async_register(
            DOMAIN, SERVICE_DOSE, handle_dose, schema=SERVICE_DOSE_SCHEMA
        )

    return True


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register the static path for brand icons."""
    hass.http.register_static_path(
        f"/api/autoaqua_doser/static",
        str(Path(__file__).parent),
        cache_headers=True,
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)

        # Unregister service if no more entries
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, SERVICE_DOSE)
            hass.data.pop(DOMAIN, None)

    return unload_ok
