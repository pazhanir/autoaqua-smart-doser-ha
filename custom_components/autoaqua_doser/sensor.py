"""Sensor entities for Auto Aqua Smart Doser."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import AutoAquaDoserCoordinator, DoserDeviceData

SENSOR_DESCRIPTIONS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="online_status",
        name="Status",
        icon="mdi:connection",
    ),
    SensorEntityDescription(
        key="firmware_version",
        name="Firmware",
        icon="mdi:information-outline",
        entity_registry_enabled_default=True,
    ),
    SensorEntityDescription(
        key="tank_name",
        name="Tank",
        icon="mdi:fishbowl-outline",
    ),
    # Raw status frame + cloud device data, for decoding more fields.
    SensorEntityDescription(
        key="status_hex",
        name="Status Raw",
        icon="mdi:code-braces",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
)

# Left out of the raw attributes: account identifiers and secrets, the status
# frame (already the state), and *date* fields, which change on every poll and
# would write a recorder row each minute.
_EXCLUDED_KEYS = ("device_uaccount", "device_uid", "tank_id", "device_status_hex")
_EXCLUDED_PARTS = ("token", "password", "secret", "session", "date")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities from a config entry."""
    coordinator: AutoAquaDoserCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        AutoAquaDoserSensor(coordinator, description)
        for description in SENSOR_DESCRIPTIONS
    )


class AutoAquaDoserSensor(
    CoordinatorEntity[AutoAquaDoserCoordinator], SensorEntity
):
    """Sensor entity for doser device info."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: AutoAquaDoserCoordinator,
        description: SensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.device_id}_{description.key}"

    @property
    def device_info(self) -> dict:
        """Return device info to link this entity to the device."""
        data: DoserDeviceData = self.coordinator.data
        return {
            "identifiers": {(DOMAIN, self.coordinator.device_id)},
            "name": data.device_name,
            "manufacturer": MANUFACTURER,
            "model": MODEL,
            "sw_version": data.firmware_version,
        }

    @property
    def native_value(self) -> str | None:
        """Return the sensor value."""
        data: DoserDeviceData = self.coordinator.data
        key = self.entity_description.key

        if key == "online_status":
            return "Online" if data.online else "Offline"
        if key == "firmware_version":
            return data.firmware_version
        if key == "tank_name":
            return data.tank_name or "Unknown"
        if key == "status_hex":
            return data.status_hex[:255] or None
        return None

    @property
    def extra_state_attributes(self) -> dict | None:
        """Expose the raw cloud device data on the diagnostic sensor only."""
        if self.entity_description.key != "status_hex":
            return None
        raw = self.coordinator.data.raw or {}
        return {
            k: v
            for k, v in raw.items()
            if k not in _EXCLUDED_KEYS
            and not any(part in k.lower() for part in _EXCLUDED_PARTS)
        }
