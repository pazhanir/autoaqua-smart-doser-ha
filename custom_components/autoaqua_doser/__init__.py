"""The Auto Aqua Smart Doser integration."""

from __future__ import annotations

import logging
from pathlib import Path

import voluptuous as vol

from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
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
from .schedule import ScheduleManager

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.NUMBER, Platform.BUTTON]

# ── Dose service ──────────────────────────────────────────────────────

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

# ── Schedule services ─────────────────────────────────────────────────

SERVICE_ADD_SCHEDULE = "add_schedule"
SERVICE_UPDATE_SCHEDULE = "update_schedule"
SERVICE_REMOVE_SCHEDULE = "remove_schedule"
SERVICE_TOGGLE_SCHEDULE = "toggle_schedule"
SERVICE_RENAME_PUMP = "rename_pump"

ATTR_SCHEDULE_ID = "schedule_id"
ATTR_TIME = "time"
ATTR_DAYS = "days"
ATTR_ENABLED = "enabled"
ATTR_NAME = "name"

SERVICE_ADD_SCHEDULE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): str,
        vol.Required(ATTR_PUMP): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=PUMP_COUNT)
        ),
        vol.Required(ATTR_ML): vol.All(
            vol.Coerce(int), vol.Range(min=DOSE_MIN_ML, max=DOSE_MAX_ML)
        ),
        vol.Required(ATTR_TIME): str,
        vol.Optional(ATTR_DAYS, default=[]): vol.All(
            cv.ensure_list, [vol.In(["mon", "tue", "wed", "thu", "fri", "sat", "sun"])]
        ),
        vol.Optional(ATTR_ENABLED, default=True): bool,
        vol.Optional(ATTR_NAME, default=""): str,
    }
)

SERVICE_UPDATE_SCHEDULE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): str,
        vol.Required(ATTR_SCHEDULE_ID): str,
        vol.Optional(ATTR_PUMP): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=PUMP_COUNT)
        ),
        vol.Optional(ATTR_ML): vol.All(
            vol.Coerce(int), vol.Range(min=DOSE_MIN_ML, max=DOSE_MAX_ML)
        ),
        vol.Optional(ATTR_TIME): str,
        vol.Optional(ATTR_DAYS): vol.All(
            cv.ensure_list, [vol.In(["mon", "tue", "wed", "thu", "fri", "sat", "sun"])]
        ),
        vol.Optional(ATTR_ENABLED): bool,
        vol.Optional(ATTR_NAME): str,
    }
)

SERVICE_REMOVE_SCHEDULE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): str,
        vol.Required(ATTR_SCHEDULE_ID): str,
    }
)

SERVICE_TOGGLE_SCHEDULE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): str,
        vol.Required(ATTR_SCHEDULE_ID): str,
    }
)

SERVICE_RENAME_PUMP_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): str,
        vol.Required(ATTR_PUMP): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=PUMP_COUNT)
        ),
        vol.Required(ATTR_NAME): str,
    }
)

# Key for storing the schedule manager per device
SCHEDULE_MANAGERS_KEY = f"{DOMAIN}_schedule_managers"

# Static path for serving the Lovelace card JS
CARD_URL_PATH = f"/hacsfiles/{DOMAIN}"
CARD_JS_FILENAME = "autoaqua-doser-schedule-card.js"
CARD_VERSION = "1.1.1"
LOVELACE_RESOURCE_URL = f"{CARD_URL_PATH}/{CARD_JS_FILENAME}?v={CARD_VERSION}"

# Keys for per-hass-instance registration flags
_CARD_REGISTERED_KEY = f"{DOMAIN}_card_registered"
_WS_REGISTERED_KEY = f"{DOMAIN}_ws_registered"


def _get_schedule_manager(hass: HomeAssistant, device_id: str) -> ScheduleManager | None:
    """Find the ScheduleManager for a given device_id."""
    managers: dict[str, ScheduleManager] = hass.data.get(SCHEDULE_MANAGERS_KEY, {})
    return managers.get(device_id)


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
    device_id = entry.data[CONF_DEVICE_ID]
    coordinator = AutoAquaDoserCoordinator(
        hass=hass,
        api=api,
        device_id=device_id,
    )
    await coordinator.async_config_entry_first_refresh()

    # Store coordinator for platforms to access
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # ── Schedule Manager ──────────────────────────────────────────────
    schedule_mgr = ScheduleManager(hass, device_id)
    await schedule_mgr.async_load()

    hass.data.setdefault(SCHEDULE_MANAGERS_KEY, {})
    hass.data[SCHEDULE_MANAGERS_KEY][device_id] = schedule_mgr

    # Set up entity platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # ── Register services (once, shared across all config entries) ────
    await _async_register_services(hass)

    # ── Register WebSocket command ────────────────────────────────────
    _register_websocket_commands(hass)

    # ── Serve card JS as a static path ────────────────────────────────
    await _async_register_card_resource(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)

        # Shutdown schedule manager for this device
        device_id = entry.data[CONF_DEVICE_ID]
        managers: dict[str, ScheduleManager] = hass.data.get(SCHEDULE_MANAGERS_KEY, {})
        mgr = managers.pop(device_id, None)
        if mgr:
            mgr.async_shutdown()
        if not managers:
            hass.data.pop(SCHEDULE_MANAGERS_KEY, None)

        # Unregister services and clean up if no more entries
        if not hass.data[DOMAIN]:
            for svc in (
                SERVICE_DOSE,
                SERVICE_ADD_SCHEDULE,
                SERVICE_UPDATE_SCHEDULE,
                SERVICE_REMOVE_SCHEDULE,
                SERVICE_TOGGLE_SCHEDULE,
                SERVICE_RENAME_PUMP,
            ):
                hass.services.async_remove(DOMAIN, svc)
            hass.data.pop(DOMAIN, None)

            # Remove Lovelace resource entry
            await _async_remove_lovelace_resource(hass)

            # Reset registration flags so re-setup works correctly
            hass.data.pop(_CARD_REGISTERED_KEY, None)
            hass.data.pop(_WS_REGISTERED_KEY, None)

    return unload_ok


# ── Service registration ──────────────────────────────────────────────


async def _async_register_services(hass: HomeAssistant) -> None:
    """Register all domain services (idempotent — skips if already registered)."""

    # --- Dose service ---
    if not hass.services.has_service(DOMAIN, SERVICE_DOSE):

        async def handle_dose(call: ServiceCall) -> None:
            """Handle the autoaqua_doser.dose service call."""
            target_device_id = call.data[ATTR_DEVICE_ID]
            pump = call.data[ATTR_PUMP]
            ml = call.data[ATTR_ML]

            coord = _find_coordinator(hass, target_device_id)
            if coord is None:
                _LOGGER.error(
                    "No configured doser found with device_id %s", target_device_id
                )
                return

            await coord.async_dose(pump, ml)

        hass.services.async_register(
            DOMAIN, SERVICE_DOSE, handle_dose, schema=SERVICE_DOSE_SCHEMA
        )

    # --- Add schedule ---
    if not hass.services.has_service(DOMAIN, SERVICE_ADD_SCHEDULE):

        async def handle_add_schedule(call: ServiceCall) -> None:
            target_device_id = call.data[ATTR_DEVICE_ID]
            mgr = _get_schedule_manager(hass, target_device_id)
            if mgr is None:
                _LOGGER.error("No schedule manager for device %s", target_device_id)
                return

            try:
                await mgr.async_add(
                    pump=call.data[ATTR_PUMP],
                    ml=call.data[ATTR_ML],
                    time_str=call.data[ATTR_TIME],
                    days=call.data.get(ATTR_DAYS, []),
                    enabled=call.data.get(ATTR_ENABLED, True),
                    name=call.data.get(ATTR_NAME, ""),
                )
            except ValueError as exc:
                _LOGGER.error("Failed to add schedule: %s", exc)
                raise

        hass.services.async_register(
            DOMAIN, SERVICE_ADD_SCHEDULE, handle_add_schedule,
            schema=SERVICE_ADD_SCHEDULE_SCHEMA,
        )

    # --- Update schedule ---
    if not hass.services.has_service(DOMAIN, SERVICE_UPDATE_SCHEDULE):

        async def handle_update_schedule(call: ServiceCall) -> None:
            target_device_id = call.data[ATTR_DEVICE_ID]
            mgr = _get_schedule_manager(hass, target_device_id)
            if mgr is None:
                _LOGGER.error("No schedule manager for device %s", target_device_id)
                return

            try:
                await mgr.async_update(
                    schedule_id=call.data[ATTR_SCHEDULE_ID],
                    pump=call.data.get(ATTR_PUMP),
                    ml=call.data.get(ATTR_ML),
                    time_str=call.data.get(ATTR_TIME),
                    days=call.data.get(ATTR_DAYS),
                    enabled=call.data.get(ATTR_ENABLED),
                    name=call.data.get(ATTR_NAME),
                )
            except ValueError as exc:
                _LOGGER.error("Failed to update schedule: %s", exc)
                raise

        hass.services.async_register(
            DOMAIN, SERVICE_UPDATE_SCHEDULE, handle_update_schedule,
            schema=SERVICE_UPDATE_SCHEDULE_SCHEMA,
        )

    # --- Remove schedule ---
    if not hass.services.has_service(DOMAIN, SERVICE_REMOVE_SCHEDULE):

        async def handle_remove_schedule(call: ServiceCall) -> None:
            target_device_id = call.data[ATTR_DEVICE_ID]
            mgr = _get_schedule_manager(hass, target_device_id)
            if mgr is None:
                _LOGGER.error("No schedule manager for device %s", target_device_id)
                return

            try:
                await mgr.async_remove(call.data[ATTR_SCHEDULE_ID])
            except ValueError as exc:
                _LOGGER.error("Failed to remove schedule: %s", exc)
                raise

        hass.services.async_register(
            DOMAIN, SERVICE_REMOVE_SCHEDULE, handle_remove_schedule,
            schema=SERVICE_REMOVE_SCHEDULE_SCHEMA,
        )

    # --- Toggle schedule ---
    if not hass.services.has_service(DOMAIN, SERVICE_TOGGLE_SCHEDULE):

        async def handle_toggle_schedule(call: ServiceCall) -> None:
            target_device_id = call.data[ATTR_DEVICE_ID]
            mgr = _get_schedule_manager(hass, target_device_id)
            if mgr is None:
                _LOGGER.error("No schedule manager for device %s", target_device_id)
                return

            try:
                await mgr.async_toggle(call.data[ATTR_SCHEDULE_ID])
            except ValueError as exc:
                _LOGGER.error("Failed to toggle schedule: %s", exc)
                raise

        hass.services.async_register(
            DOMAIN, SERVICE_TOGGLE_SCHEDULE, handle_toggle_schedule,
            schema=SERVICE_TOGGLE_SCHEDULE_SCHEMA,
        )

    # --- Rename pump ---
    if not hass.services.has_service(DOMAIN, SERVICE_RENAME_PUMP):

        async def handle_rename_pump(call: ServiceCall) -> None:
            target_device_id = call.data[ATTR_DEVICE_ID]
            mgr = _get_schedule_manager(hass, target_device_id)
            if mgr is None:
                _LOGGER.error("No schedule manager for device %s", target_device_id)
                return

            try:
                await mgr.async_rename_pump(
                    pump=call.data[ATTR_PUMP],
                    name=call.data[ATTR_NAME],
                )
            except ValueError as exc:
                _LOGGER.error("Failed to rename pump: %s", exc)
                raise

        hass.services.async_register(
            DOMAIN, SERVICE_RENAME_PUMP, handle_rename_pump,
            schema=SERVICE_RENAME_PUMP_SCHEMA,
        )


# ── WebSocket commands ────────────────────────────────────────────────


def _register_websocket_commands(hass: HomeAssistant) -> None:
    """Register WebSocket commands (once per HA instance)."""
    if hass.data.get(_WS_REGISTERED_KEY):
        return
    hass.data[_WS_REGISTERED_KEY] = True

    from homeassistant.components import websocket_api

    @websocket_api.websocket_command(
        {
            vol.Required("type"): f"{DOMAIN}/get_schedules",
            vol.Required("device_id"): str,
        }
    )
    @websocket_api.async_response
    async def ws_get_schedules(
        hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
    ) -> None:
        """Return all schedules for a device via WebSocket."""
        device_id = msg["device_id"]
        mgr = _get_schedule_manager(hass, device_id)
        if mgr is None:
            connection.send_error(
                msg["id"], "not_found", f"No schedule manager for device {device_id}"
            )
            return
        connection.send_result(msg["id"], {"schedules": mgr.get_all()})

    websocket_api.async_register_command(hass, ws_get_schedules)

    @websocket_api.websocket_command(
        {vol.Required("type"): f"{DOMAIN}/get_devices"}
    )
    @websocket_api.async_response
    async def ws_get_devices(
        hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
    ) -> None:
        """Return all configured devices with pump names."""
        devices = []
        for _eid, obj in hass.data.get(DOMAIN, {}).items():
            if not isinstance(obj, AutoAquaDoserCoordinator):
                continue
            coord: AutoAquaDoserCoordinator = obj
            mgr = _get_schedule_manager(hass, coord.device_id)

            # Build pump names: custom name > API name > default
            pump_names = {}
            custom_names = mgr.get_pump_names() if mgr else {}
            for p in range(1, PUMP_COUNT + 1):
                if custom_names.get(p):
                    pump_names[str(p)] = custom_names[p]
                elif coord.data and coord.data.pump_names.get(p):
                    pump_names[str(p)] = coord.data.pump_names[p]
                else:
                    pump_names[str(p)] = f"Pump {p}"

            devices.append({
                "device_id": coord.device_id,
                "device_name": coord.data.device_name if coord.data else coord.device_id,
                "online": coord.data.online if coord.data else False,
                "pump_names": pump_names,
            })

        connection.send_result(msg["id"], {"devices": devices})

    websocket_api.async_register_command(hass, ws_get_devices)


# ── Static file serving for Lovelace card ─────────────────────────────


async def _async_register_card_resource(hass: HomeAssistant) -> None:
    """Register the card JS file as a static path and add it as a Lovelace resource."""
    if hass.data.get(_CARD_REGISTERED_KEY):
        return
    hass.data[_CARD_REGISTERED_KEY] = True

    # Serve the www/ folder under the URL path
    www_dir = str(Path(__file__).parent / "www")
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL_PATH, www_dir, cache_headers=False)]
    )
    _LOGGER.info("Registered static path %s -> %s", CARD_URL_PATH, www_dir)

    # Auto-register as a Lovelace resource so users don't have to manually add it
    # We use the lovelace resources collection if available
    await _async_add_lovelace_resource(hass)


async def _async_add_lovelace_resource(hass: HomeAssistant) -> None:
    """Add the card JS as a Lovelace resource if not already present.

    If an older version URL exists, update it to the current version.
    """
    try:
        # Try to access the Lovelace resources collection (storage mode)
        from homeassistant.components.lovelace import (
            DOMAIN as LOVELACE_DOMAIN,
        )
        from homeassistant.components.lovelace.resources import (
            ResourceStorageCollection,
        )

        lovelace_data = hass.data.get(LOVELACE_DOMAIN)
        if lovelace_data is None:
            _LOGGER.debug("Lovelace not loaded yet; skipping auto-register of card resource")
            return

        # In storage mode, lovelace_data has a resources attribute
        resources = getattr(lovelace_data, "resources", None)
        if resources is None or not isinstance(resources, ResourceStorageCollection):
            _LOGGER.debug("Lovelace not in storage mode; add card resource manually")
            return

        # Ensure resources are loaded
        if not resources.loaded:
            await resources.async_load()

        # Check if already registered (exact match or older version)
        base_url = f"{CARD_URL_PATH}/{CARD_JS_FILENAME}"
        for item in resources.async_items():
            url = item.get("url", "")
            if url == LOVELACE_RESOURCE_URL:
                _LOGGER.debug("Card resource already registered with current version")
                return
            if url.startswith(base_url):
                # Older version found — update to current
                await resources.async_update_item(
                    item["id"], {"res_type": "module", "url": LOVELACE_RESOURCE_URL}
                )
                _LOGGER.info(
                    "Updated Lovelace resource URL: %s -> %s", url, LOVELACE_RESOURCE_URL
                )
                return

        # Register it
        await resources.async_create_item(
            {"res_type": "module", "url": LOVELACE_RESOURCE_URL}
        )
        _LOGGER.info("Auto-registered Lovelace resource: %s", LOVELACE_RESOURCE_URL)

    except (ImportError, AttributeError, KeyError) as exc:
        _LOGGER.debug(
            "Could not auto-register Lovelace resource (%s); add manually: %s",
            exc,
            LOVELACE_RESOURCE_URL,
        )
    except Exception:
        _LOGGER.warning(
            "Unexpected error registering Lovelace resource; add manually: %s",
            LOVELACE_RESOURCE_URL,
            exc_info=True,
        )


async def _async_remove_lovelace_resource(hass: HomeAssistant) -> None:
    """Remove the card JS Lovelace resource entry on unload."""
    try:
        from homeassistant.components.lovelace import (
            DOMAIN as LOVELACE_DOMAIN,
        )
        from homeassistant.components.lovelace.resources import (
            ResourceStorageCollection,
        )

        lovelace_data = hass.data.get(LOVELACE_DOMAIN)
        if lovelace_data is None:
            return

        resources = getattr(lovelace_data, "resources", None)
        if resources is None or not isinstance(resources, ResourceStorageCollection):
            return

        if not resources.loaded:
            await resources.async_load()

        base_url = f"{CARD_URL_PATH}/{CARD_JS_FILENAME}"
        for item in resources.async_items():
            if item.get("url", "").startswith(base_url):
                await resources.async_delete_item(item["id"])
                _LOGGER.info("Removed Lovelace resource: %s", item["url"])
                return

    except Exception:
        _LOGGER.debug("Could not remove Lovelace resource on unload", exc_info=True)


# ── Helpers ───────────────────────────────────────────────────────────


def _find_coordinator(
    hass: HomeAssistant, device_id: str
) -> AutoAquaDoserCoordinator | None:
    """Find the coordinator for a given device_id."""
    for _eid, c in hass.data.get(DOMAIN, {}).items():
        if isinstance(c, AutoAquaDoserCoordinator) and c.device_id == device_id:
            return c
    return None
