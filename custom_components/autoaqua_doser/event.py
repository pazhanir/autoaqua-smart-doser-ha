"""Event entities for Auto Aqua Smart Doser (dose execution history)."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MANUFACTURER, MODEL, PUMP_COUNT, SIGNAL_DOSE_EXECUTED
from .coordinator import AutoAquaDoserCoordinator, DoserDeviceData

_LOGGER = logging.getLogger(__name__)

EVENT_DOSE_EXECUTED = "dose_executed"
EVENT_DOSE_FAILED = "dose_failed"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up event entities from a config entry."""
    coordinator: AutoAquaDoserCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        AutoAquaDoseEvent(coordinator, pump)
        for pump in range(1, PUMP_COUNT + 1)
    )


class AutoAquaDoseEvent(EventEntity):
    """Event entity that records dose executions for a pump.

    Each dose (scheduled or manual) fires an event that appears on the
    device page logbook and can trigger automations.
    """

    _attr_has_entity_name = True
    _attr_event_types = [EVENT_DOSE_EXECUTED, EVENT_DOSE_FAILED]
    _attr_icon = "mdi:history"

    def __init__(
        self,
        coordinator: AutoAquaDoserCoordinator,
        pump: int,
    ) -> None:
        """Initialize the event entity."""
        self._coordinator = coordinator
        self._pump = pump
        self._attr_unique_id = f"{coordinator.device_id}_pump_{pump}_dose_event"

    @property
    def name(self) -> str:
        """Return the entity name."""
        data: DoserDeviceData = self._coordinator.data
        pump_name = data.pump_names.get(self._pump, f"Pump {self._pump}")
        return f"{pump_name} Dose Activity"

    @property
    def device_info(self) -> dict:
        """Return device info to link this entity to the device."""
        data: DoserDeviceData = self._coordinator.data
        return {
            "identifiers": {(DOMAIN, self._coordinator.device_id)},
            "name": data.device_name,
            "manufacturer": MANUFACTURER,
            "model": MODEL,
            "sw_version": data.firmware_version,
        }

    async def async_added_to_hass(self) -> None:
        """Connect to dispatcher signal when entity is added."""
        signal = SIGNAL_DOSE_EXECUTED.format(
            device_id=self._coordinator.device_id, pump=self._pump
        )
        self.async_on_remove(
            async_dispatcher_connect(self.hass, signal, self._handle_dose_event)
        )

    @callback
    def _handle_dose_event(self, data: dict[str, Any]) -> None:
        """Handle a dose event from the dispatcher.

        Called by the coordinator after a dose command succeeds or fails.
        """
        event_type = data.get("event_type", EVENT_DOSE_EXECUTED)
        event_data: dict[str, Any] = {
            "ml": data.get("ml", 0),
            "trigger": data.get("trigger", "manual"),
        }

        schedule_name = data.get("schedule_name", "")
        if schedule_name:
            event_data["schedule_name"] = schedule_name

        error = data.get("error")
        if error:
            event_data["error"] = error

        _LOGGER.debug(
            "Dose event for pump %d: %s %s", self._pump, event_type, event_data
        )
        self._trigger_event(event_type, event_data)
        self.async_write_ha_state()
