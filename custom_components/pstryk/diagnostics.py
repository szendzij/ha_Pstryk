"""Diagnostics support for Pstryk Energy."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    diagnostics_data = {
        "entry": {
            "title": entry.title,
            "entry_id": entry.entry_id,
            "version": entry.version,
            "options": entry.options,
        },
        "coordinators": {},
    }

    for price_type in ("buy", "sell"):
        key = f"{entry.entry_id}_{price_type}"
        coordinator = hass.data[DOMAIN].get(key)
        if coordinator:
            coordinator_data = {
                "last_update_success": coordinator.last_update_success,
                "data_available": coordinator.data is not None
            }
            
            # Sprawdzamy czy atrybut istnieje przed użyciem
            if hasattr(coordinator, 'last_update') and coordinator.last_update:
                coordinator_data["last_update"] = dt_util.as_local(coordinator.last_update).isoformat()
            elif hasattr(coordinator, 'last_updated') and coordinator.last_updated:
                coordinator_data["last_update"] = dt_util.as_local(coordinator.last_updated).isoformat()
            else:
                coordinator_data["last_update"] = None
                
            diagnostics_data["coordinators"][price_type] = coordinator_data

    return diagnostics_data
