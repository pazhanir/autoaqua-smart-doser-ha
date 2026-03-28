"""Number entities for Auto Aqua Smart Doser (dose amount per pump)."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, DOSE_MAX_ML, DOSE_MIN_ML, MANUFACTURER, MODEL, PUMP_COUNT
from .coordinator import AutoAquaDoserCoordinator, DoserDeviceData


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up number entities from a config entry."""
    coordinator: AutoAquaDoserCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        AutoAquaDoseAmountNumber(coordinator, pump)
        for pump in range(1, PUMP_COUNT + 1)
    )


class AutoAquaDoseAmountNumber(
    CoordinatorEntity[AutoAquaDoserCoordinator], NumberEntity
):
    """Number entity to set the dose amount (ml) for a pump.

    This does NOT trigger dosing — it just stores the amount.
    Press the corresponding button entity (or call the service) to dose.
    """

    _attr_has_entity_name = True
    _attr_native_min_value = DOSE_MIN_ML
    _attr_native_max_value = DOSE_MAX_ML
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX
    _attr_native_unit_of_measurement = "ml"
    _attr_icon = "mdi:beaker-outline"

    def __init__(
        self,
        coordinator: AutoAquaDoserCoordinator,
        pump: int,
    ) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator)
        self._pump = pump
        self._dose_ml: float = DOSE_MIN_ML
        self._attr_unique_id = f"{coordinator.device_id}_pump_{pump}_dose_amount"

    @property
    def name(self) -> str:
        """Return the entity name."""
        data: DoserDeviceData = self.coordinator.data
        pump_name = data.pump_names.get(self._pump, f"Pump {self._pump}")
        return f"{pump_name} Dose Amount"

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

    @property
    def native_value(self) -> float:
        """Return the current dose amount."""
        return self._dose_ml

    async def async_set_native_value(self, value: float) -> None:
        """Set the dose amount (stored locally, not sent to device)."""
        self._dose_ml = int(value)

    @property
    def pump_number(self) -> int:
        """Return the pump number for this entity."""
        return self._pump

    @property
    def dose_ml(self) -> int:
        """Return the currently set dose amount as integer ml."""
        return int(self._dose_ml)
