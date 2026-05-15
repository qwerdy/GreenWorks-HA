"""Config flow for the GreenWorks integration."""
import voluptuous as vol
import logging
import homeassistant.helpers.config_validation as cv
from typing import Any
from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.data_entry_flow import FlowResult
from .greenworks_api.GreenWorksAPI import UnauthorizedException, GreenWorksAPI
from .const import CONF_MOWER_NAME, DOMAIN

_LOGGER = logging.getLogger(__name__)

AUTH_SCHEMA = vol.Schema(
    {vol.Required(CONF_EMAIL): cv.string, vol.Required(CONF_PASSWORD): cv.string}
)

class GreenworksConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Greenworks config flow."""

    def __init__(self) -> None:
        """Initialize the Hass config flow."""
        super().__init__()
        self._email = None
        self._password = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Invoke when a user initiates a flow via the user interface."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._email = user_input[CONF_EMAIL]
            self._password = user_input[CONF_PASSWORD]
            # Return the form of the next step.
            return await self.async_step_device()

        return self.async_show_form(
            step_id="user", data_schema=AUTH_SCHEMA, errors=errors
        )

    async def async_step_device(self, data: dict[str, Any] | None = None):
        """Second step in config flow to choose the device."""
        if data is not None:
            data[CONF_EMAIL] = self._email
            data[CONF_PASSWORD] = self._password
            return await self.async_create_entry(title=data[CONF_MOWER_NAME], data=data)

        errors = {}
        try:
            api = await self.hass.async_add_executor_job(
                GreenWorksAPI, self._email, self._password, self.hass.config.time_zone
            )
        except UnauthorizedException:
            errors["base"] = "auth_error"
            return self.async_show_form(
                step_id="user", data_schema=AUTH_SCHEMA, errors=errors)

        if self._email is None or self._password is None:
            errors["base"] = "auth_error"
            return self.async_show_form(step_id="user", data_schema=AUTH_SCHEMA, errors=errors)
        
        try:
            mowers = await self.hass.async_add_executor_job(api.get_devices)
        except UnauthorizedException as ex:
            errors["base"] = "auth_error"
            _LOGGER.error("Unauthorized error fetching devices", ex, exc_info=True, stack_info=True)
            return self.async_show_form(step_id="user", data_schema=AUTH_SCHEMA, errors=errors)
        except Exception as ex:
            _LOGGER.error("Error fetching devices: %s", ex)
            errors["base"] = "unknown_error"
            return self.async_show_form(step_id="user", data_schema=AUTH_SCHEMA, errors=errors)

        all_mowers = {m.name for m in mowers}

        DEVICE_SCHEMA = vol.Schema(
            {vol.Optional(CONF_MOWER_NAME): vol.In(all_mowers)}
        )

        return self.async_show_form(step_id="device", data_schema=DEVICE_SCHEMA, errors=errors)

    async def async_step_reauth(self, user_input=None):
        """Handle re-authentication step in the config flow."""
        return await self.async_step_user()

    async def async_create_entry(self, title: str, data: dict) -> FlowResult:
        """Create an oauth config entry or update existing entry for reauth."""
        # TODO: This example supports only a single config entry. Consider
        # any special handling needed for multiple config entries.
        existing_entry = await self.async_set_unique_id(data[CONF_MOWER_NAME])
        if existing_entry:
            self.hass.config_entries.async_update_entry(existing_entry, data=data)
            await self.hass.config_entries.async_reload(existing_entry.entry_id)
            return self.async_abort(reason="reauth_successful")
        return super().async_create_entry(title=title, data=data)