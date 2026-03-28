"""Config flow for Auto Aqua Smart Doser integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD

from .api import ApiConnectionError, AuthenticationError, AutoAquaApi
from .const import CONF_DEVICE_ID, CONF_DEVICE_NAME, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class AutoAquaDoserConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Auto Aqua Smart Doser."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._devices: list[dict[str, Any]] = []
        self._email: str = ""
        self._password: str = ""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial credentials step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._email = user_input[CONF_EMAIL]
            self._password = user_input[CONF_PASSWORD]

            api = AutoAquaApi(self._email, self._password)
            try:
                await api.authenticate()
                self._devices = await api.get_devices()
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except ApiConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during setup")
                errors["base"] = "unknown"
            finally:
                await api.close()

            if not errors:
                if not self._devices:
                    errors["base"] = "no_devices"
                elif len(self._devices) == 1:
                    # Single device — skip device selection
                    device = self._devices[0]
                    return await self._create_entry(device)
                else:
                    # Multiple devices — let the user pick
                    return await self.async_step_device()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )

    async def async_step_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle device selection when multiple devices are found."""
        if user_input is not None:
            device_id = user_input[CONF_DEVICE_ID]
            device = next(
                (d for d in self._devices if d["device_id"] == device_id),
                self._devices[0],
            )
            return await self._create_entry(device)

        device_options = {
            d["device_id"]: f"{d.get('device_name', d['device_id'])} ({d.get('tank_name', 'No tank')})"
            for d in self._devices
        }

        return self.async_show_form(
            step_id="device",
            data_schema=vol.Schema(
                {vol.Required(CONF_DEVICE_ID): vol.In(device_options)}
            ),
        )

    async def _create_entry(self, device: dict[str, Any]) -> ConfigFlowResult:
        """Create the config entry for a device."""
        device_id = device["device_id"]

        # Prevent duplicate entries for the same device
        await self.async_set_unique_id(device_id)
        self._abort_if_unique_id_configured()

        device_name = device.get("device_name", f"Doser {device_id}")

        return self.async_create_entry(
            title=device_name,
            data={
                CONF_EMAIL: self._email,
                CONF_PASSWORD: self._password,
                CONF_DEVICE_ID: device_id,
                CONF_DEVICE_NAME: device_name,
            },
        )
