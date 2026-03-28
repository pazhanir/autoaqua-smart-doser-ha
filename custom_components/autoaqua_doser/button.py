"""Button entities for Auto Aqua Smart Doser (trigger dose per pump)."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL, PUMP_COUNT
from .coordinator import AutoAquaDoserCoordinator, DoserDeviceData
from .number import AutoAquaDoseAmountNumber

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up button entities from a config entry."""
    coordinator: AutoAquaDoserCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        AutoAquaDoseButton(coordinator, pump, entry.entry_id)
        for pump in range(1, PUMP_COUNT + 1)
    )


class AutoAquaDoseButton(
    CoordinatorEntity[AutoAquaDoserCoordinator], ButtonEntity
):
    """Button entity to trigger dosing for a pump.

    Reads the dose amount from the corresponding number entity,
    then sends the dose command to the device.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:pump"

    def __init__(
        self,
        coordinator: AutoAquaDoserCoordinator,
        pump: int,
        entry_id: str,
    ) -> None:
        """Initialize the button entity."""
        super().__init__(coordinator)
        self._pump = pump
        self._entry_id = entry_id
        self._attr_unique_id = f"{coordinator.device_id}_pump_{pump}_dose_button"

    @property
    def name(self) -> str:
        """Return the entity name."""
        data: DoserDeviceData = self.coordinator.data
        pump_name = data.pump_names.get(self._pump, f"Pump {self._pump}")
        return f"{pump_name} Dose"

    @property
    def device_info(self) -> dict:
        """Return device info."""
        data: DoserDeviceData = self.coordinator.data
        return {
            "identifiers": {(DOMAIN, self.coordinator.device_id)},
            "name": data.device_name,
            "manufacturer": MANUFACTURER,
            "model": MODEL,
            "sw_version": data.firmware_version,
        }

    def _find_number_entity(self) -> AutoAquaDoseAmountNumber | None:
        """Find the matching dose amount number entity for this pump."""
        entity_registry = self.hass.data.get("entity_registry")
        if entity_registry is None:
            return None

        # Look up through the entity component for number entities
        number_component = self.hass.data.get("entity_components", {}).get("number")
        if number_component is None:
            return None

        for entity in number_component.entities:
            if (
                isinstance(entity, AutoAquaDoseAmountNumber)
                and entity.pump_number == self._pump
                and entity.unique_id
                and self.coordinator.device_id in entity.unique_id
            ):
                return entity
        return None

    async def async_press(self) -> None:
        """Handle the button press — trigger a dose.

        Reads the dose amount from the corresponding number entity.
        Defaults to 1 ml if the number entity is not found.
        """
        # Find the dose amount from the paired number entity
        dose_ml = 1  # Safe default

        number_entity = self._find_number_entity()
        if number_entity is not None:
            dose_ml = number_entity.dose_ml
            _LOGGER.debug(
                "Pump %d: found dose amount %d ml from number entity",
                self._pump,
                dose_ml,
            )
        else:
            _LOGGER.warning(
                "Pump %d: could not find number entity, using default %d ml",
                self._pump,
                dose_ml,
            )

        await self.coordinator.async_dose(self._pump, dose_ml)
