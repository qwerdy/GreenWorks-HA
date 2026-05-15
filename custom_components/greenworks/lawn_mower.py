"""GreenWorks lawn_mower platform: exposes GreenWorks mowers as Home Assistant lawn mower entities."""

from __future__ import annotations

from typing import Any, cast
import logging

try:
    from homeassistant.components import lawn_mower as lm  # type: ignore[reportMissingImports]
    LawnMowerActivity = lm.LawnMowerActivity  # type: ignore[attr-defined]
    LawnMowerEntity = lm.LawnMowerEntity  # type: ignore[attr-defined]
    LawnMowerEntityFeature = lm.LawnMowerEntityFeature  # type: ignore[attr-defined]
except Exception:  # pragma: no cover - allows local linting without HA installed
    from .const import LawnMowerActivity, LawnMowerEntityFeature  # type: ignore

    class LawnMowerEntity:  # type: ignore
        pass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_MOWER_NAME, DOMAIN
from . import GreenWorksDataCoordinator
from .greenworks_api.GreenWorksAPI import Mower

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    """Set up GreenWorks lawn mower entity for a config entry."""
    mower_name: str = cast(str, entry.data.get(CONF_MOWER_NAME, ""))
    key = "coordinator" + mower_name

    coordinator: GreenWorksDataCoordinator = hass.data[DOMAIN][key]

    # Find the mower matching the selected name
    target = next((m for m in coordinator.mower if m.name == mower_name), None)
    if target is None:
        _LOGGER.warning("No mower named '%s' found; delaying entity creation until data refresh.", mower_name)

    entity = GreenWorksMowerEntity(coordinator, mower_name)
    async_add_entities([entity], update_before_add=True)


class GreenWorksMowerEntity(CoordinatorEntity, LawnMowerEntity):  # type: ignore[misc]
    """Representation of a GreenWorks mower."""

    def __init__(self, coordinator: GreenWorksDataCoordinator, mower_name: str) -> None:
        super().__init__(coordinator)
        self._mower_name = mower_name
        self._attr_name = mower_name
        # unique_id should be stable; fallback to name if we can't resolve id yet
        self._attr_unique_id = f"greenworks_{mower_name}"
        # Remove control abilities: do not advertise any supported features
        self._attr_supported_features = LawnMowerEntityFeature(0)

        # Try to set a better unique_id if available from current data
        mower = self._current_mower
        if mower is not None:
            uid = getattr(mower, "sn", None) or getattr(mower, "id", None)
            if uid is not None:
                self._attr_unique_id = str(uid)

    # Helpers
    @property
    def _current_mower(self) -> Mower | None:
        """Return the latest mower object matching this entity."""
        data = self.coordinator.data or []
        for m in data:
            try:
                if getattr(m, "name", None) == self._mower_name:
                    return m
            except Exception:  # pragma: no cover - defensive
                continue
        return None

    # Entity properties
    @property
    def available(self) -> bool:
        mower = self._current_mower
        base_available = bool(super().available)
        mower_online = bool(getattr(mower, "is_online", True)) if mower is not None else False
        return base_available and mower_online

    @property
    def device_info(self) -> dict[str, Any]:
        mower = self._current_mower
        identifiers = {(
            DOMAIN,
            str(getattr(mower, "sn", None) or getattr(mower, "id", self._mower_name)),
        )}
        return {
            "identifiers": identifiers,
            "manufacturer": "GreenWorks",
            "model": getattr(mower, "model", "GreenWorks Mower"),
            "name": self._mower_name,
            # Firmware version not available on Mower dataclass; leave empty
            "sw_version": "",
        }

    @property
    def activity(self) -> Any | None:
        mower = self._current_mower

        if mower is None:
            return None

        # Attempt to read state from various likely attributes
        state = None
        try:
            # Common patterns: mower.operating_status.mower_main_state, mower.state, mower.status
            operating_status = getattr(mower, "operating_status", None)
            if operating_status is not None:
                state = getattr(operating_status, "mower_main_state", None)
            if state is None:
                state = getattr(mower, "mower_main_state", None)
            if state is None:
                state = getattr(mower, "state", None)
            if state is None:
                state = getattr(mower, "status", None)
        except Exception:  # pragma: no cover - defensive
            state = None

        # Normalize enum-like to string name
        if state is not None and hasattr(state, "name"):
            state_name: str = str(getattr(state, "name"))
        else:
            state_name = str(state).upper() if state is not None else "UNKNOWN"

        # Map vendor states to HA activities
        mapping: dict[str, Any] = {
            "MOWING": LawnMowerActivity.MOWING,
            "LEAVING_CHARGING_STATION": LawnMowerActivity.MOWING,
            "CHARGING": LawnMowerActivity.DOCKED,
            "PARKED_BY_USER": LawnMowerActivity.DOCKED,
            "SEARCHING_FOR_CHARGING_STATION": LawnMowerActivity.RETURNING, # type: ignore
            "PAUSED": LawnMowerActivity.PAUSED,
            "STOP_BUTTON_PRESSED": LawnMowerActivity.ERROR,
            
        }
        return mapping.get(state_name)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional mower attributes such as battery and schedule."""
        mower = self._current_mower
        if mower is None:
            return None
        attrs: dict[str, Any] = {}
        # Battery level from operating_status
        try:
            operating_status = getattr(mower, "operating_status", None)
            if operating_status is not None:
                battery = getattr(operating_status, "battery_status", None)
                if battery is not None:
                    attrs["battery_level"] = battery
                next_start = getattr(operating_status, "next_start", None)
                if next_start is not None:
                    attrs["next_start"] = getattr(next_start, "isoformat", lambda: str(next_start))()
                request_time = getattr(operating_status, "request_time", None)
                if request_time is not None:
                    attrs["request_time"] = getattr(request_time, "isoformat", lambda: str(request_time))()
        except Exception:  # pragma: no cover
            pass
        return attrs

