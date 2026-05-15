"""Green Works integration for Home Assistant."""

from datetime import timedelta
import logging
from typing import Final
import io
import contextlib

from homeassistant import config_entries, core
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from .greenworks_api.GreenWorksAPI import GreenWorksAPI, Mower, UnauthorizedException
from .const import CONF_MOWER_NAME, DOMAIN

_LOGGER = logging.getLogger(__name__)
_LOGGER.warning("🚀 Greenworks integration is loading! (warning)")
_LOGGER.debug("🐞 Debug logging is working in Greenworks.")

PLATFORMS: Final = ["lawn_mower", "sensor", "binary_sensor"]

async def async_setup_entry(hass: core.HomeAssistant, entry: config_entries.ConfigEntry) -> bool:
    """Set up Green Works from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    
    try:
        api = await hass.async_add_executor_job(GreenWorksAPI, entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD], hass.config.time_zone)
    except UnauthorizedException as err:
        raise ConfigEntryAuthFailed(err) from err

    coordinator = GreenWorksDataCoordinator(hass, api, entry.data[CONF_MOWER_NAME])
    hass.data[DOMAIN]["coordinator" + entry.data[CONF_MOWER_NAME]] = coordinator

    await coordinator.async_config_entry_first_refresh()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: core.HomeAssistant, entry: config_entries.ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop("coordinator" + entry.data[CONF_MOWER_NAME])

    return unload_ok

class GreenWorksDataCoordinator(DataUpdateCoordinator):
    """Get and update the latest data."""

    def __init__(self, hass: core.HomeAssistant, api: GreenWorksAPI, mower_name) -> None:
        """Initialize the GreenWorksDataCoordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name="GreenWorksData",
            update_interval=timedelta(seconds=60),
        )
        self.api = api
        self.mower_name = mower_name
        self._mower:list[Mower]

    @property
    def mower(self) -> list[Mower]:
        """Return the mower data."""
        return self.data if self.data else []

    async def _async_update_data(self):
        """Fetch data from API endpoint."""
        try:
            _LOGGER.debug("Fetching data from GreenWorks API")
            # Capture stdout from the third-party library (which uses print) so it appears in HA logs
            def _call_with_captured_stdout():
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    result = self.api.get_devices()
                out = buf.getvalue()
                if out:
                    _LOGGER.debug("GreenWorksAPI stdout (get_devices):\n%s", out.strip())
                return result

            self._mower = await self.hass.async_add_executor_job(_call_with_captured_stdout)
            _LOGGER.debug("Fetched %d mowers: %s", len(self._mower), [m.name for m in self._mower])
            return self._mower
        except KeyError as ex:
            _LOGGER.error("KeyError calling GreenWorks API: %s", ex)
            raise UpdateFailed("Problems calling GreenWorks") from ex
        except Exception as ex:
            _LOGGER.error("Unexpected error calling GreenWorks API: %s", ex)
            raise UpdateFailed("Problems calling GreenWorks") from ex