"""Schedule manager for Auto Aqua Smart Doser.

Handles CRUD for dosing schedules, persistent storage, and time-based
execution via Home Assistant's async_track_time_change.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.storage import Store

from .const import DOMAIN, DOSE_MAX_ML, DOSE_MIN_ML, PUMP_COUNT

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY = f"{DOMAIN}_schedules"
STORAGE_VERSION = 1

VALID_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DAY_INDEX_MAP = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


@dataclass
class ScheduleEntry:
    """A single dosing schedule entry."""

    id: str
    pump: int
    ml: int
    time: str  # "HH:MM"
    days: list[str]  # e.g. ["mon", "wed", "fri"], empty or all 7 = daily
    enabled: bool = True
    name: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to a JSON-serializable dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScheduleEntry:
        """Create from a dict (loaded from storage)."""
        return cls(
            id=data["id"],
            pump=data["pump"],
            ml=data["ml"],
            time=data["time"],
            days=data.get("days", []),
            enabled=data.get("enabled", True),
            name=data.get("name", ""),
        )

    @property
    def hour(self) -> int:
        """Parse hour from time string."""
        return int(self.time.split(":")[0])

    @property
    def minute(self) -> int:
        """Parse minute from time string."""
        return int(self.time.split(":")[1])

    @property
    def is_daily(self) -> bool:
        """Return True if the schedule runs every day."""
        return len(self.days) == 0 or len(self.days) == 7

    def matches_day(self, weekday: int) -> bool:
        """Check if this schedule should run on the given weekday (0=Mon, 6=Sun)."""
        if self.is_daily:
            return True
        return any(DAY_INDEX_MAP.get(d) == weekday for d in self.days)


def _validate_schedule_data(
    pump: int, ml: int, time_str: str, days: list[str]
) -> None:
    """Validate schedule parameters. Raises ValueError on bad input."""
    if pump < 1 or pump > PUMP_COUNT:
        raise ValueError(f"Pump must be 1-{PUMP_COUNT}, got {pump}")
    if ml < DOSE_MIN_ML or ml > DOSE_MAX_ML:
        raise ValueError(f"ML must be {DOSE_MIN_ML}-{DOSE_MAX_ML}, got {ml}")

    # Validate time format
    parts = time_str.split(":")
    if len(parts) != 2:
        raise ValueError(f"Time must be HH:MM, got {time_str}")
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise ValueError(f"Time must be HH:MM with integers, got {time_str}") from exc
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError(f"Time out of range: {time_str}")

    # Validate days
    for d in days:
        if d not in VALID_DAYS:
            raise ValueError(f"Invalid day '{d}', must be one of {VALID_DAYS}")


class ScheduleManager:
    """Manage dosing schedules with persistent storage and time-based execution."""

    def __init__(self, hass: HomeAssistant, device_id: str) -> None:
        """Initialize the schedule manager.

        Args:
            hass: Home Assistant instance.
            device_id: Device ID for finding the coordinator.
        """
        self.hass = hass
        self.device_id = device_id
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._schedules: dict[str, ScheduleEntry] = {}
        self._listeners: dict[str, CALLBACK_TYPE] = {}
        self._pump_names: dict[int, str] = {}  # {1: "Alkalinity", 2: "Calcium", ...}
        self._save_lock = asyncio.Lock()

    async def async_load(self) -> None:
        """Load schedules and pump names from persistent storage and register listeners."""
        data = await self._store.async_load()
        if data and isinstance(data, dict):
            device_data = data.get(self.device_id)
            if isinstance(device_data, dict):
                # New format: {schedules: [...], pump_names: {...}}
                for entry_data in device_data.get("schedules", []):
                    try:
                        entry = ScheduleEntry.from_dict(entry_data)
                        self._schedules[entry.id] = entry
                    except (KeyError, ValueError) as exc:
                        _LOGGER.warning("Skipping invalid schedule entry: %s", exc)
                raw_names = device_data.get("pump_names", {})
                self._pump_names = {int(k): v for k, v in raw_names.items()}
            elif isinstance(device_data, list):
                # Legacy format (v1): just a list of schedules
                for entry_data in device_data:
                    try:
                        entry = ScheduleEntry.from_dict(entry_data)
                        self._schedules[entry.id] = entry
                    except (KeyError, ValueError) as exc:
                        _LOGGER.warning("Skipping invalid schedule entry: %s", exc)

        # Register time listeners for all enabled schedules
        self._register_all_listeners()
        _LOGGER.info(
            "Loaded %d schedules for device %s",
            len(self._schedules),
            self.device_id,
        )

    async def _async_save(self) -> None:
        """Save all schedules and pump names to persistent storage."""
        async with self._save_lock:
            # Load existing data to preserve other devices' data
            data = await self._store.async_load() or {}
            data[self.device_id] = {
                "schedules": [s.to_dict() for s in self._schedules.values()],
                "pump_names": {str(k): v for k, v in self._pump_names.items()},
            }
            await self._store.async_save(data)

    # ── Pump names ────────────────────────────────────────────────────

    def get_pump_names(self) -> dict[int, str]:
        """Return custom pump names. Missing pumps have no entry."""
        return dict(self._pump_names)

    async def async_rename_pump(self, pump: int, name: str) -> None:
        """Set a custom name for a pump. Empty string clears the name."""
        if pump < 1 or pump > PUMP_COUNT:
            raise ValueError(f"Pump must be 1-{PUMP_COUNT}, got {pump}")
        if name:
            self._pump_names[pump] = name
        else:
            self._pump_names.pop(pump, None)
        await self._async_save()
        _LOGGER.info("Renamed pump %d to '%s' on device %s", pump, name, self.device_id)

    def get_all(self) -> list[dict[str, Any]]:
        """Return all schedules as a list of dicts."""
        return [s.to_dict() for s in self._schedules.values()]

    def get_by_pump(self, pump: int) -> list[dict[str, Any]]:
        """Return schedules for a specific pump."""
        return [s.to_dict() for s in self._schedules.values() if s.pump == pump]

    def get_by_id(self, schedule_id: str) -> ScheduleEntry | None:
        """Return a schedule by ID."""
        return self._schedules.get(schedule_id)

    def _check_overlap(
        self, time_str: str, days: list[str], exclude_id: str | None = None
    ) -> str | None:
        """Check if a schedule at the given time/days would overlap with any existing one.

        Only one pump can dose at a time, so two schedules at the exact same
        minute are forbidden regardless of pump.

        Returns the conflicting schedule's name/id if overlap found, else None.
        """
        for existing in self._schedules.values():
            if exclude_id and existing.id == exclude_id:
                continue
            if not existing.enabled:
                continue
            if existing.time != time_str:
                continue

            # Same time — check if days overlap
            new_daily = len(days) == 0 or len(days) == 7
            existing_daily = existing.is_daily

            if new_daily or existing_daily:
                # One or both are daily — guaranteed overlap
                label = existing.name or existing.id
                return f"Conflicts with '{label}' (Pump {existing.pump} at {existing.time})"

            # Both have specific days — check intersection
            if set(days) & set(existing.days):
                label = existing.name or existing.id
                return f"Conflicts with '{label}' (Pump {existing.pump} at {existing.time})"

        return None

    async def async_add(
        self,
        pump: int,
        ml: int,
        time_str: str,
        days: list[str],
        enabled: bool = True,
        name: str = "",
    ) -> ScheduleEntry:
        """Add a new schedule entry.

        Raises ValueError if the schedule overlaps or has invalid parameters.
        """
        _validate_schedule_data(pump, ml, time_str, days)

        if enabled:
            conflict = self._check_overlap(time_str, days)
            if conflict:
                raise ValueError(f"Schedule overlap: {conflict}")

        entry = ScheduleEntry(
            id=str(uuid.uuid4()),
            pump=pump,
            ml=ml,
            time=time_str,
            days=days,
            enabled=enabled,
            name=name,
        )

        self._schedules[entry.id] = entry
        await self._async_save()

        if entry.enabled:
            self._register_listener(entry)

        _LOGGER.info("Added schedule: %s (pump %d, %dml at %s)", entry.id, pump, ml, time_str)
        return entry

    async def async_update(
        self,
        schedule_id: str,
        pump: int | None = None,
        ml: int | None = None,
        time_str: str | None = None,
        days: list[str] | None = None,
        enabled: bool | None = None,
        name: str | None = None,
    ) -> ScheduleEntry:
        """Update an existing schedule entry.

        Raises ValueError if not found, overlaps, or has invalid parameters.
        """
        entry = self._schedules.get(schedule_id)
        if entry is None:
            raise ValueError(f"Schedule {schedule_id} not found")

        # Apply updates
        new_pump = pump if pump is not None else entry.pump
        new_ml = ml if ml is not None else entry.ml
        new_time = time_str if time_str is not None else entry.time
        new_days = days if days is not None else entry.days
        new_enabled = enabled if enabled is not None else entry.enabled
        new_name = name if name is not None else entry.name

        _validate_schedule_data(new_pump, new_ml, new_time, new_days)

        if new_enabled:
            conflict = self._check_overlap(new_time, new_days, exclude_id=schedule_id)
            if conflict:
                raise ValueError(f"Schedule overlap: {conflict}")

        # Unregister old listener
        self._unregister_listener(schedule_id)

        # Apply
        entry.pump = new_pump
        entry.ml = new_ml
        entry.time = new_time
        entry.days = new_days
        entry.enabled = new_enabled
        entry.name = new_name

        await self._async_save()

        if entry.enabled:
            self._register_listener(entry)

        _LOGGER.info("Updated schedule: %s", schedule_id)
        return entry

    async def async_remove(self, schedule_id: str) -> None:
        """Remove a schedule entry. Raises ValueError if not found."""
        if schedule_id not in self._schedules:
            raise ValueError(f"Schedule {schedule_id} not found")

        self._unregister_listener(schedule_id)
        del self._schedules[schedule_id]
        await self._async_save()
        _LOGGER.info("Removed schedule: %s", schedule_id)

    async def async_toggle(self, schedule_id: str) -> ScheduleEntry:
        """Toggle a schedule's enabled state. Raises ValueError if not found."""
        entry = self._schedules.get(schedule_id)
        if entry is None:
            raise ValueError(f"Schedule {schedule_id} not found")

        new_enabled = not entry.enabled

        # If enabling, check for overlaps
        if new_enabled:
            conflict = self._check_overlap(entry.time, entry.days, exclude_id=schedule_id)
            if conflict:
                raise ValueError(f"Cannot enable: {conflict}")

        self._unregister_listener(schedule_id)
        entry.enabled = new_enabled

        if entry.enabled:
            self._register_listener(entry)

        await self._async_save()
        _LOGGER.info("Toggled schedule %s -> enabled=%s", schedule_id, entry.enabled)
        return entry

    # ── Time-based execution ──────────────────────────────────────────

    @callback
    def _register_all_listeners(self) -> None:
        """Register time listeners for all enabled schedules."""
        for entry in self._schedules.values():
            if entry.enabled:
                self._register_listener(entry)

    @callback
    def _register_listener(self, entry: ScheduleEntry) -> None:
        """Register an async_track_time_change listener for one schedule."""
        # Remove existing listener if any
        self._unregister_listener(entry.id)

        unsub = async_track_time_change(
            self.hass,
            self._make_time_callback(entry.id),
            hour=entry.hour,
            minute=entry.minute,
            second=0,
        )
        self._listeners[entry.id] = unsub
        _LOGGER.debug(
            "Registered listener for schedule %s at %s", entry.id, entry.time
        )

    @callback
    def _unregister_listener(self, schedule_id: str) -> None:
        """Unregister a time listener for a schedule."""
        unsub = self._listeners.pop(schedule_id, None)
        if unsub:
            unsub()
            _LOGGER.debug("Unregistered listener for schedule %s", schedule_id)

    def _make_time_callback(self, schedule_id: str):
        """Create a time callback closure for a specific schedule."""

        async def _on_time(now: datetime) -> None:
            """Called when the clock hits the schedule's time."""
            entry = self._schedules.get(schedule_id)
            if entry is None or not entry.enabled:
                return

            # Check day of week (0=Monday in Python, matches our DAY_INDEX_MAP)
            if not entry.matches_day(now.weekday()):
                _LOGGER.debug(
                    "Schedule %s skipped: today is %s, schedule days: %s",
                    schedule_id,
                    now.strftime("%a"),
                    entry.days,
                )
                return

            # Find the coordinator for this device
            from .coordinator import AutoAquaDoserCoordinator

            coordinator: AutoAquaDoserCoordinator | None = None
            for _eid, obj in self.hass.data.get(DOMAIN, {}).items():
                if (
                    isinstance(obj, AutoAquaDoserCoordinator)
                    and obj.device_id == self.device_id
                ):
                    coordinator = obj
                    break

            if coordinator is None:
                _LOGGER.error(
                    "Schedule %s fired but no coordinator found for device %s",
                    schedule_id,
                    self.device_id,
                )
                return

            _LOGGER.info(
                "Schedule '%s' triggered: dosing pump %d with %d ml",
                entry.name or entry.id,
                entry.pump,
                entry.ml,
            )
            try:
                await coordinator.async_dose(entry.pump, entry.ml)
            except Exception:
                _LOGGER.exception(
                    "Schedule %s failed to dose pump %d", schedule_id, entry.pump
                )

        return _on_time

    # ── Cleanup ───────────────────────────────────────────────────────

    @callback
    def async_shutdown(self) -> None:
        """Unregister all listeners on integration unload."""
        for unsub in self._listeners.values():
            unsub()
        self._listeners.clear()
        _LOGGER.info("Schedule manager shut down for device %s", self.device_id)
