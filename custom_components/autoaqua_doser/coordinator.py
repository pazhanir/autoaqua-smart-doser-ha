"""DataUpdateCoordinator for Auto Aqua Smart Doser."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AutoAquaApi, AutoAquaApiError
from .const import (
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    PUMP_COUNT,
    STATUS_POLL_CMD,
    build_dose_command,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class DoserDeviceData:
    """Parsed device data from the API."""

    device_id: str = ""
    device_name: str = ""
    device_type: str = ""
    device_mac: str = ""
    online: bool = False
    firmware_hex: str = ""
    firmware_version: str = ""
    status_hex: str = ""
    tank_name: str = ""
    pump_names: dict[int, str] = field(default_factory=dict)
    calibrations: dict[int, int] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


def _parse_firmware(fw_hex: str) -> str:
    """Parse firmware version from the device_fw_hex string.

    Example: '8099000119020E0000' -> extract version bytes.
    The firmware hex starts with 80 99 00 01, followed by version data.
    Bytes at positions 8-9 (after header): major, minor, patch in decimal.
    """
    if not fw_hex or len(fw_hex) < 14:
        return "unknown"
    try:
        # Header is 8 chars '80990001', version data follows
        version_data = fw_hex[8:]
        # Observed: '19020E0000' -> 0x19=25, 0x02=2, 0x0E=14
        major = int(version_data[0:2], 16)
        minor = int(version_data[2:4], 16)
        patch = int(version_data[4:6], 16)
        return f"{major}.{minor}.{patch}"
    except (ValueError, IndexError):
        return fw_hex


def _parse_device(raw: dict[str, Any]) -> DoserDeviceData:
    """Parse raw API device dict into structured data."""
    fw_hex = raw.get("device_fw_hex") or ""
    pump_names: dict[int, str] = {}
    calibrations: dict[int, int] = {}

    for i in range(1, PUMP_COUNT + 1):
        name = raw.get(f"pump_name{i}")
        pump_names[i] = name if name else f"Pump {i}"
        calibrations[i] = raw.get(f"calibrate{i}", 0)

    return DoserDeviceData(
        device_id=raw.get("device_id", ""),
        device_name=raw.get("device_name", ""),
        device_type=raw.get("device_type", ""),
        device_mac=raw.get("device_mac", ""),
        online=raw.get("device_online_status") == 1,
        firmware_hex=fw_hex,
        firmware_version=_parse_firmware(fw_hex),
        status_hex=raw.get("device_status_hex") or "",
        tank_name=raw.get("tank_name", ""),
        pump_names=pump_names,
        calibrations=calibrations,
        raw=raw,
    )


class AutoAquaDoserCoordinator(DataUpdateCoordinator[DoserDeviceData]):
    """Coordinator that polls the AutoAqua cloud API every 60 seconds."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        api: AutoAquaApi,
        device_id: str,
    ) -> None:
        """Initialize the coordinator.

        Args:
            hass: Home Assistant instance.
            api: Authenticated AutoAqua API client.
            device_id: MAC / ID of the target doser device.
        """
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
        )
        self.api = api
        self.device_id = device_id

    async def _async_update_data(self) -> DoserDeviceData:
        """Fetch device data from the cloud API.

        Also sends a status poll command so the device reports fresh data.
        """
        try:
            # Send status poll so device pushes updated state to the cloud
            await self.api.send_command(self.device_id, STATUS_POLL_CMD)

            # Fetch all devices and find ours
            devices = await self.api.get_devices()
            device_raw = next(
                (d for d in devices if d.get("device_id") == self.device_id),
                None,
            )

            if device_raw is None:
                raise UpdateFailed(
                    f"Device {self.device_id} not found in API response"
                )

            return _parse_device(device_raw)

        except AutoAquaApiError as err:
            raise UpdateFailed(f"Error fetching doser data: {err}") from err

    async def async_dose(self, pump: int, ml: int) -> bool:
        """Send a dose command for the given pump and amount.

        Args:
            pump: Pump number (1-4).
            ml: Milliliters to dose (1-999).

        Returns True if the command was acknowledged.
        """
        command = build_dose_command(pump, ml)
        _LOGGER.info(
            "Dosing pump %d with %d ml on device %s (cmd: %s)",
            pump,
            ml,
            self.device_id,
            command,
        )
        result = await self.api.send_command(self.device_id, command)

        # Request a refresh so sensors update after dosing
        await self.async_request_refresh()

        return result
