"""Binary sensor entities for Auto Aqua Smart Doser (liquid sensor per pump)."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL, PUMP_COUNT
from .coordinator import AutoAquaDoserCoordinator, DoserDeviceData


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up liquid sensor entities from a config entry."""
    coordinator: AutoAquaDoserCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        AutoAquaLiquidMissingSensor(coordinator, pump)
        for pump in range(1, PUMP_COUNT + 1)
    )


class AutoAquaLiquidMissingSensor(
    CoordinatorEntity[AutoAquaDoserCoordinator], RestoreEntity, BinarySensorEntity
):
    """On when the pump's optical sensor sees no liquid (empty bottle or lost prime).

    The device only reports this while it is dosing or running manually, so the
    value is the last one seen during activity. After a restart, the previous
    state is restored until the next dose of this doser.
    """

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: AutoAquaDoserCoordinator, pump: int) -> None:
        """Initialize the liquid sensor entity."""
        super().__init__(coordinator)
        self._pump = pump
        self._restored: bool | None = None
        self._attr_unique_id = f"{coordinator.device_id}_pump_{pump}_liquid_missing"

    @property
    def name(self) -> str:
        """Return the entity name."""
        data: DoserDeviceData = self.coordinator.data
        pump_name = data.pump_names.get(self._pump, f"Pump {self._pump}")
        return f"{pump_name} Liquid Missing"

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

    async def async_added_to_hass(self) -> None:
        """Restore the last known state until the device reports activity."""
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in ("on", "off"):
            self._restored = last.state == "on"

    @property
    def is_on(self) -> bool | None:
        """Return True when liquid is missing at this pump."""
        liquid_missing = self.coordinator.liquid_missing
        if liquid_missing is not None:
            return liquid_missing.get(self._pump)
        return self._restored
