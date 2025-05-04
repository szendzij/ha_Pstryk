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

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
) -> None:
    """Set up the Pstryk sensors via the coordinator."""
    api_key = hass.data[DOMAIN][entry.entry_id]["api_key"]

    entities = []
    for price_type in ("buy", "sell"):
        coordinator = PstrykDataUpdateCoordinator(hass, api_key, price_type)
        await coordinator.async_config_entry_first_refresh()
        entities.append(PstrykPriceSensor(coordinator, price_type))
        if price_type == "buy":  # Add energy usage sensor only once
            entities.append(PstrykEnergyUsageSensor(coordinator))

    async_add_entities(entities)

    # Register update listener for option changes - only if not already registered
    if not entry.update_listeners:
        entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    
    await hass.config_entries.async_forward_entry_setup(entry, "sensor")
    _LOGGER.debug("Pstryk entry setup: %s", entry.entry_id)
    return True

async def _cleanup_coordinators(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Clean up coordinators and cancel scheduled tasks."""
    for price_type in ("buy", "sell"):
        key = f"{entry.entry_id}_{price_type}"
        coordinator = hass.data[DOMAIN].get(key)
        if coordinator:
            _LOGGER.debug("Cleaning up %s coordinator for entry %s", price_type, entry.entry_id)
            # Cancel scheduled updates
            if hasattr(coordinator, '_unsub_hourly') and coordinator._unsub_hourly:
                coordinator._unsub_hourly()
                coordinator._unsub_hourly = None
            if hasattr(coordinator, '_unsub_midnight') and coordinator._unsub_midnight:
                coordinator._unsub_midnight()
                coordinator._unsub_midnight = None
            # Remove from hass data
            hass.data[DOMAIN].pop(key, None)

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload sensor platform and clear data."""
    # First cancel coordinators' scheduled updates
    await _cleanup_coordinators(hass, entry)
    
    # Then unload the platform
    unload_ok = await hass.config_entries.async_forward_entry_unload(entry, "sensor")
    
    # Finally clean up data
    if unload_ok:
        if entry.entry_id in hass.data[DOMAIN]:
            hass.data[DOMAIN].pop(entry.entry_id)
            
        # Clean up any remaining components
        for key in list(hass.data[DOMAIN].keys()):
            if key.startswith(f"{entry.entry_id}_"):
                hass.data[DOMAIN].pop(key, None)
                
    return unload_ok

async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry when options change."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
