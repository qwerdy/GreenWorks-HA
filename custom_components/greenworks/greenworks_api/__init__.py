import logging
# Ensure library logging integrates with host app (e.g., Home Assistant)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry):
    _LOGGER.info("Initializing GreenWorksAPI client")  # Now will show
    return True