"""Pstryk Energy integration."""
import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Only set up hass.data structure (no YAML config)."""
    hass.data.setdefault(DOMAIN, {})
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Store API key and forward to sensor platform."""
    hass.data[DOMAIN].setdefault(entry.entry_id, {})["api_key"] = entry.data.get("api_key")
    
    # Register update listener for option changes - only if not already registered
    if not entry.update_listeners:
        entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    
    await hass.config_entries.async_forward_entry_setup(entry, "sensor")
    _LOGGER.debug("Pstryk entry setup: %s", entry.entry_id)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload sensor platform and clear data."""
    # First cancel coordinators' scheduled updates
    for price_type in ("buy", "sell"):
        key = f"{entry.entry_id}_{price_type}"
        coordinator = hass.data[DOMAIN].get(key)
        if coordinator:
            if hasattr(coordinator, '_unsub_hourly') and coordinator._unsub_hourly:
                coordinator._unsub_hourly()
            if hasattr(coordinator, '_unsub_midnight') and coordinator._unsub_midnight:
                coordinator._unsub_midnight()
    
    # Then unload the platform
    unload_ok = await hass.config_entries.async_forward_entry_unload(entry, "sensor")
    
    # Finally clean up data
    if unload_ok:
        if entry.entry_id in hass.data[DOMAIN]:
            hass.data[DOMAIN].pop(entry.entry_id)
            
        # Clean up any coordinators
        for key in list(hass.data[DOMAIN].keys()):
            if key.startswith(f"{entry.entry_id}_"):
                hass.data[DOMAIN].pop(key, None)
                
    return unload_ok

async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry when options change."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
